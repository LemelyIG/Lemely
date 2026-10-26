import type { PublicDirectoryParams, DirectoryParams, TimeOfDay } from "@/lib/tutoring/queryKeys"
import type { AvailabilityRule, TutoringMode } from "@/lib/tutoringTypes"

/*
 * T22 · the pure half of finding and booking a tutor (G-16, G-17, S-33, S-34,
 * S-35 and, later, P-07): filter state and its address, the lists on the page,
 * and the fixed copy those screens share. Nothing here touches the DOM, so the
 * node-only runner tests it (`tutoringDiscovery.test.ts`), and the SPEC
 * sentences below are compared with the SPEC text there.
 *
 * ── Filters live in the address ─────────────────────────────────────────────
 *
 * A filtered directory is a link a parent can send a student. The address
 * carries exactly the API's own parameter names (`subject`, `mode` repeated,
 * `area`, `minRating`, `day` repeated, `timeOfDay` repeated), written in one
 * canonical order, so the same filters are always the same address and a
 * round trip changes nothing. Anything in an address the API would refuse, or
 * that is not one of the options, is dropped on the way in rather than sent.
 * The public directory has no availability filter (P1, row 5b), so `day` and
 * `timeOfDay` are neither read from nor written to a public address.
 */

export type Audience = "public" | "member"

export interface DirectoryFilterState {
  subject: string
  modes: TutoringMode[]
  area: string
  /** 1.0 to 5.0 in steps of 0.5 (P1), or null for any rating. */
  minRating: number | null
  /** ISO weekdays, Monday = 1, ascending. Member directory only. */
  days: number[]
  timesOfDay: TimeOfDay[]
}

export const EMPTY_FILTERS: DirectoryFilterState = {
  subject: "",
  modes: [],
  area: "",
  minRating: null,
  days: [],
  timesOfDay: [],
}

// ── Options ─────────────────────────────────────────────────────────────────

export const MODE_OPTIONS: readonly { value: TutoringMode; label: string }[] = [
  { value: "virtual", label: "Virtual" },
  { value: "in_person", label: "In person" },
  { value: "other", label: "Other" },
]

/** Time-of-day buckets as the API reads them (tutor-zone wall clock, SPEC §b.2). */
export const TIME_OF_DAY_OPTIONS: readonly { value: TimeOfDay; label: string; hours: string }[] = [
  { value: "morning", label: "Morning", hours: "06:00–12:00" },
  { value: "afternoon", label: "Afternoon", hours: "12:00–17:00" },
  { value: "evening", label: "Evening", hours: "17:00–22:00" },
]

export const WEEKDAYS: readonly { value: number; short: string; long: string }[] = [
  { value: 1, short: "Mon", long: "Monday" },
  { value: 2, short: "Tue", long: "Tuesday" },
  { value: 3, short: "Wed", long: "Wednesday" },
  { value: 4, short: "Thu", long: "Thursday" },
  { value: 5, short: "Fri", long: "Friday" },
  { value: 6, short: "Sat", long: "Saturday" },
  { value: 7, short: "Sun", long: "Sunday" },
]

/** The minimum ratings offered. P1 accepts any step of 0.5 from 1.0 to 5.0; below 3 is not a useful floor. */
export const RATING_OPTIONS: readonly number[] = [3, 3.5, 4, 4.5]

const MODES: ReadonlySet<string> = new Set(MODE_OPTIONS.map((o) => o.value))
const TIMES: ReadonlySet<string> = new Set(TIME_OF_DAY_OPTIONS.map((o) => o.value))

// ── Address <-> state ───────────────────────────────────────────────────────

function parseRating(raw: string | null): number | null {
  if (raw === null || raw.trim() === "") return null
  const value = Number(raw)
  if (!Number.isFinite(value) || value < 1 || value > 5 || (value * 2) % 1 !== 0) return null
  return value
}

/** Distinct values in the order of `canonical`, dropping everything not in it. */
function inCanonicalOrder<T extends string | number>(values: readonly T[], canonical: readonly T[]): T[] {
  const wanted = new Set(values)
  return canonical.filter((value) => wanted.has(value))
}

/** The filters an address describes. Values that are not options are ignored. */
export function filtersFromSearchParams(params: URLSearchParams, audience: Audience): DirectoryFilterState {
  const modes = params.getAll("mode").filter((m): m is TutoringMode => MODES.has(m))
  const state: DirectoryFilterState = {
    subject: params.get("subject")?.trim() ?? "",
    modes: inCanonicalOrder(
      modes,
      MODE_OPTIONS.map((o) => o.value),
    ),
    area: params.get("area")?.trim() ?? "",
    minRating: parseRating(params.get("minRating")),
    days: [],
    timesOfDay: [],
  }
  if (audience === "member") {
    const days = params
      .getAll("day")
      .map((d) => (/^[1-7]$/.test(d) ? Number(d) : null))
      .filter((d): d is number => d !== null)
    state.days = inCanonicalOrder(
      days,
      WEEKDAYS.map((w) => w.value),
    )
    state.timesOfDay = inCanonicalOrder(
      params.getAll("timeOfDay").filter((t): t is TimeOfDay => TIMES.has(t)),
      TIME_OF_DAY_OPTIONS.map((o) => o.value),
    )
  }
  return state
}

/** The address for these filters: canonical order, nothing for an unset filter. */
export function filtersToSearchParams(filters: DirectoryFilterState, audience: Audience): URLSearchParams {
  const params = new URLSearchParams()
  if (filters.subject !== "") params.set("subject", filters.subject)
  for (const mode of inCanonicalOrder(
    filters.modes,
    MODE_OPTIONS.map((o) => o.value),
  )) {
    params.append("mode", mode)
  }
  if (filters.area !== "") params.set("area", filters.area)
  if (filters.minRating !== null) params.set("minRating", String(filters.minRating))
  if (audience === "member") {
    for (const day of inCanonicalOrder(
      filters.days,
      WEEKDAYS.map((w) => w.value),
    )) {
      params.append("day", String(day))
    }
    for (const time of inCanonicalOrder(
      filters.timesOfDay,
      TIME_OF_DAY_OPTIONS.map((o) => o.value),
    )) {
      params.append("timeOfDay", time)
    }
  }
  return params
}

/** The request for one page of P1 (public) or SP1 (member). Only set filters are sent. */
export function directoryQuery(
  filters: DirectoryFilterState,
  audience: Audience,
  cursor?: string | null,
): PublicDirectoryParams | DirectoryParams {
  const query: DirectoryParams = {}
  if (filters.subject !== "") query.subject = filters.subject
  if (filters.modes.length > 0) query.mode = [...filters.modes]
  if (filters.area !== "") query.area = filters.area
  if (filters.minRating !== null) query.minRating = filters.minRating
  if (audience === "member") {
    if (filters.days.length > 0) query.day = [...filters.days]
    if (filters.timesOfDay.length > 0) query.timeOfDay = [...filters.timesOfDay]
  }
  if (cursor) query.cursor = cursor
  return query
}

/** How many choices are set (each chosen mode, day and time counts once). */
export function activeFilterCount(filters: DirectoryFilterState, audience: Audience): number {
  let count = filters.modes.length
  if (filters.subject !== "") count += 1
  if (filters.area !== "") count += 1
  if (filters.minRating !== null) count += 1
  if (audience === "member") count += filters.days.length + filters.timesOfDay.length
  return count
}

export function hasActiveFilters(filters: DirectoryFilterState, audience: Audience): boolean {
  return activeFilterCount(filters, audience) > 0
}

// ── Lists ───────────────────────────────────────────────────────────────────

/** `next` appended to `items`, skipping any whose key is already there (a tutor can move between pages). */
export function appendUnique<T>(items: readonly T[], next: readonly T[], keyOf: (item: T) => string): T[] {
  const seen = new Set(items.map(keyOf))
  const merged = [...items]
  for (const item of next) {
    const key = keyOf(item)
    if (seen.has(key)) continue
    seen.add(key)
    merged.push(item)
  }
  return merged
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

/** "Mar 2026" from the API's "2026-03", or null (a profile not yet through its first review). */
export function listedSinceLabel(listedSince: string | null): string | null {
  if (listedSince === null) return null
  const match = /^(\d{4})-(0[1-9]|1[0-2])$/.exec(listedSince)
  if (!match) return null
  return `${MONTHS[Number(match[2]) - 1]} ${match[1]}`
}

/** "17:00" from minutes after midnight; 1440 is "24:00", the end of a day. */
export function minuteLabel(minutes: number): string {
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  return `${String(hours).padStart(2, "0")}:${String(rest).padStart(2, "0")}`
}

export interface AvailabilityRow {
  isoWeekday: number
  dayLabel: string
  /** "17:00–18:30", earliest first. Empty for a day with no rule. */
  ranges: string[]
}

/** The weekly rules as seven rows, Monday first. A day with no rule is a row with no ranges, not a gap. */
export function availabilityRows(rules: readonly AvailabilityRule[]): AvailabilityRow[] {
  return WEEKDAYS.map((day) => ({
    isoWeekday: day.value,
    dayLabel: day.long,
    ranges: rules
      .filter((rule) => rule.isoWeekday === day.value)
      .sort((a, b) => a.startMinute - b.startMinute)
      .map((rule) => `${minuteLabel(rule.startMinute)}–${minuteLabel(rule.endMinute)}`),
  }))
}

// ── Booking window ──────────────────────────────────────────────────────────

/** SP5 `days`: 14 by default, up to 28 behind "Show later dates". */
export function slotWindow(showLater: boolean): 14 | 28 {
  return showLater ? 28 : 14
}

/**
 * Today's date, "YYYY-MM-DD", on the wall clock of `zone`. SP5 takes `from` in
 * the tutor's zone, so a student in another city must ask from the tutor's
 * today. An unknown zone name reads as UTC rather than throwing.
 */
export function todayInZone(zone: string, now: Date): string {
  const parts = (timeZone: string) =>
    new Intl.DateTimeFormat("en-CA", { timeZone, year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(
      now,
    )
  let found: Intl.DateTimeFormatPart[]
  try {
    found = parts(zone)
  } catch {
    found = parts("UTC")
  }
  const get = (type: string) => found.find((p) => p.type === type)?.value ?? ""
  return `${get("year")}-${get("month")}-${get("day")}`
}

// ── Fixed copy ──────────────────────────────────────────────────────────────

export const FEES_LINE = "Fees are agreed with the tutor, outside Lemely."

/** G-16 */
export const DIRECTORY_INTRO = `Find a tutor for IGCSE Maths, Additional Maths and Physics. ${FEES_LINE}`
export const DIRECTORY_SIGN_IN_LINE = "Sign in to see full profiles, availability, reviews and results."
export const DIRECTORY_EMPTY_HEADING = "No tutors match these filters yet."
export const PLATFORM_EMPTY_HEADING = "Tutors are being reviewed. Check back soon."

/** S-33 (F10) */
export const GRADE_RANKING_NOTE =
  "Tutors with few reviews are ranked as if they also had five 4-star reviews, so one great review can't put someone at the top."

/** S-34, under both figures of every subject. */
export function resultsCaption(duringWindowDays: number, beforeLookbackDays: number): string {
  return (
    `Grades from papers uploaded in the ${duringWindowDays} days from each student's first session with this tutor, ` +
    `compared with their latest grade in the ${beforeLookbackDays} days before it. ` +
    "Grades worked out from estimated grade boundaries are left out. " +
    "These grades come from Lemely's automatic marking, which is not as accurate as an examiner. " +
    "Students choose their tutors, so this doesn't show what the tutor caused."
  )
}

/** S-34 header: the badge and its disclosure. */
export const DOCUMENTS_SEEN_LABEL = "Documents seen by Lemely"
export const DOCUMENTS_SEEN_DISCLOSURE =
  "A Lemely admin looked at documents this tutor uploaded. This is not a background check."

/** S-34 states. */
export const NO_REVIEWS_LINE = "No reviews yet."

/** S-35 (row 8b), as the student reads it. */
export const COUNTING_NOTICE_STUDENT =
  "If you have sessions with this tutor, your grades in this subject are counted, without your name, in their results. You can opt out in Tutors & your data."

/**
 * The same notice phrased for a child, when a parent books (P-07). A parent
 * cannot opt out for the child, so it says where the child can.
 */
export function countingNotice(audience: "student" | "parent", childName?: string): string {
  if (audience === "student") return COUNTING_NOTICE_STUDENT
  const name = childName && childName.trim() !== "" ? childName.trim() : "your child"
  return (
    `If ${name} has sessions with this tutor, ${name}'s grades in this subject are counted, without their name, in the tutor's results. ` +
    `${name} can opt out under Tutors & your data in their own account.`
  )
}

/** S-38's explainer, read again before sharing (S-34 "Share my progress"). */
export const SHARE_EXPLAINER =
  "Your grades, predicted grades, target grades, papers' marks, weak topics, trend, at-risk warnings and the days you were active, for all subjects. Never your answer sheets, and never the time of day you used Lemely."
export const SHARE_PARENTS_LINE =
  "Your linked parents can see who you share with and each time a tutor looked."
