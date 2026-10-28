/*
 * T-17 · pure logic of the weekly availability editor (SPEC §d, §a.2, §a.4).
 *
 * The editor shows seven days, each with any number of time windows. The API
 * stores `AvailabilityRule`s: an ISO weekday (Monday = 1) and a start and end
 * in minutes from midnight, in the tutor's own zone, on a 15-minute grid, and
 * never across midnight (`end_minute <= 1440`, `end_minute > start_minute`).
 * "A window crossing midnight is two rules" (SPEC §a.2), so this module is the
 * place where the screen's windows and the stored rules are converted.
 *
 *   - A window is a start and an end on one day. When the end is earlier than
 *     the start it ends the next day, and `rulesFromWeek` stores it as two
 *     rules: the first day from the start to 24:00, the next day from 00:00 to
 *     the end. Sunday wraps to Monday.
 *   - A window that ends exactly at midnight is the end option "24:00", not a
 *     crossing, and stays one rule.
 *   - Rules read back from the server are never merged: the two halves of a
 *     window that crossed midnight come back as two rows on two days, which is
 *     what is stored. The screen says so (`SPLIT_NOTE_LINE`).
 *   - Validation mirrors the table CHECKs and the exclusion constraint: quarter
 *     hours, inside the day, not empty, no overlap (windows may touch). It
 *     judges the split rules, so a late window can collide with an early one
 *     the next day. The server stays authoritative (422 `overlapping_rules`,
 *     `invalid_rules`).
 *
 * Wall-clock minutes in the tutor's zone are all this module knows. It does not
 * touch instants or daylight saving: the server turns rules into bookable slots
 * and offers nothing inside the repeated or missing hour (SPEC §i.4), which is
 * what `DST_NOTE_FOR` tells the tutor.
 *
 * Copy here is fixed by the SPEC and compared with it by
 * `tests/unit/tutoringAvailabilityEditor.test.ts`.
 */

import type { AvailabilityRule } from "@/lib/tutoringTypes"

export type IsoWeekday = 1 | 2 | 3 | 4 | 5 | 6 | 7

/** One window on one day, in minutes from midnight. `endMinute < startMinute` ends the next day. */
export interface DayRange {
  /** Stable key for the row; not sent to the server. */
  id: string
  startMinute: number
  endMinute: number
}

export type WeekDraft = Record<IsoWeekday, DayRange[]>

/** Quarter hours (SPEC §a.2: `start_minute % 15 = 0`). */
export const STEP_MINUTES = 15
export const MINUTES_PER_DAY = 24 * 60
/** At most 42 weekly rules (SPEC §a.2, T5), counted after the midnight split. */
export const MAX_RULES = 42

export const WEEKDAYS: readonly { iso: IsoWeekday; label: string; short: string }[] = [
  { iso: 1, label: "Monday", short: "Mon" },
  { iso: 2, label: "Tuesday", short: "Tue" },
  { iso: 3, label: "Wednesday", short: "Wed" },
  { iso: 4, label: "Thursday", short: "Thu" },
  { iso: 5, label: "Friday", short: "Fri" },
  { iso: 6, label: "Saturday", short: "Sat" },
  { iso: 7, label: "Sunday", short: "Sun" },
]

const ISO_DAYS: readonly IsoWeekday[] = [1, 2, 3, 4, 5, 6, 7]

/** SPEC T-17: the daylight saving sentence, with the tutor's zone label in front. */
export function DST_NOTE_FOR(zoneLabel: string): string {
  return `${zoneLabel}; daylight saving is handled for you. Times in the hour when the clocks change can't be booked.`
}

/** SPEC T-17, states: no rules yet. */
export const NO_RULES_LINE = "Add at least one time so students can book."

/** Shown once, under the days: how a window across midnight is stored. */
export const SPLIT_NOTE_LINE =
  "A window that goes past midnight is saved as two: one ending at midnight and one starting at midnight the next day."

// ── Clock times ─────────────────────────────────────────────────────────────

/** Minutes from midnight as "09:15"; the end of the day is "24:00". */
export function formatMinute(minute: number): string {
  const hours = Math.floor(minute / 60)
  const minutes = minute % 60
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}`
}

/** 00:00 to 23:45, every quarter hour. */
export function startOptions(): number[] {
  const out: number[] = []
  for (let minute = 0; minute < MINUTES_PER_DAY; minute += STEP_MINUTES) out.push(minute)
  return out
}

/** 00:15 to 24:00, every quarter hour. "24:00" is midnight at the end of the day. */
export function endOptions(): number[] {
  const out: number[] = []
  for (let minute = STEP_MINUTES; minute <= MINUTES_PER_DAY; minute += STEP_MINUTES) out.push(minute)
  return out
}

// ── The week ────────────────────────────────────────────────────────────────

export function emptyWeek(): WeekDraft {
  return { 1: [], 2: [], 3: [], 4: [], 5: [], 6: [], 7: [] }
}

export function crossesMidnight(range: DayRange | { startMinute: number; endMinute: number }): boolean {
  return range.endMinute < range.startMinute
}

function nextDay(weekday: number): IsoWeekday {
  return (weekday === 7 ? 1 : weekday + 1) as IsoWeekday
}

function dayLabel(weekday: number): string {
  return WEEKDAYS.find((d) => d.iso === weekday)?.label ?? ""
}

/** The stored rules for one window: one, or two when it goes past midnight. */
function splitRange(weekday: number, range: DayRange): AvailabilityRule[] {
  if (!crossesMidnight(range)) {
    return [{ isoWeekday: weekday, startMinute: range.startMinute, endMinute: range.endMinute }]
  }
  return [
    { isoWeekday: weekday, startMinute: range.startMinute, endMinute: MINUTES_PER_DAY },
    { isoWeekday: nextDay(weekday), startMinute: 0, endMinute: range.endMinute },
  ]
}

function byTime(a: AvailabilityRule, b: AvailabilityRule): number {
  return a.isoWeekday - b.isoWeekday || a.startMinute - b.startMinute || a.endMinute - b.endMinute
}

/** Every window of the week as stored rules, sorted by weekday and start. */
export function rulesFromWeek(week: WeekDraft): AvailabilityRule[] {
  const rules: AvailabilityRule[] = []
  for (const weekday of ISO_DAYS) {
    for (const range of week[weekday]) rules.push(...splitRange(weekday, range))
  }
  return rules.sort(byTime)
}

/** Stored rules as rows per day, in time order. Rows are keyed by their own times. */
export function weekFromRules(rules: readonly AvailabilityRule[]): WeekDraft {
  const week = emptyWeek()
  for (const rule of [...rules].sort(byTime)) {
    const day = week[rule.isoWeekday as IsoWeekday]
    if (!day) continue
    day.push({
      id: `saved-${rule.isoWeekday}-${rule.startMinute}-${rule.endMinute}`,
      startMinute: rule.startMinute,
      endMinute: rule.endMinute,
    })
  }
  return week
}

/** Whether the rows would save as something other than `saved`. */
export function weekIsDirty(week: WeekDraft, saved: readonly AvailabilityRule[]): boolean {
  const now = rulesFromWeek(week)
  const before = [...saved].sort(byTime)
  if (now.length !== before.length) return true
  return now.some((rule, i) => byTime(rule, before[i]) !== 0)
}

let created = 0

function nextId(): string {
  created += 1
  return `new-${created}`
}

const DEFAULT_LENGTH = 60

/**
 * A new window on a day: an hour after the day's last one if that fits, else in
 * the first free gap of an hour, else at 16:00 (and the day then reports the
 * overlap, which is honest: there was no room).
 */
export function addRange(week: WeekDraft, weekday: number): WeekDraft {
  const day = week[weekday as IsoWeekday]
  if (!day) return week
  const inDay = day.filter((r) => !crossesMidnight(r)).sort((a, b) => a.startMinute - b.startMinute)
  let start: number | null = null
  const last = inDay.at(-1)
  if (last === undefined) {
    start = 16 * 60
  } else if (last.endMinute + DEFAULT_LENGTH <= MINUTES_PER_DAY) {
    start = last.endMinute
  } else {
    let cursor = 0
    for (const range of inDay) {
      if (range.startMinute - cursor >= DEFAULT_LENGTH) {
        start = cursor
        break
      }
      cursor = Math.max(cursor, range.endMinute)
    }
  }
  const from = start ?? 16 * 60
  const row: DayRange = { id: nextId(), startMinute: from, endMinute: from + DEFAULT_LENGTH }
  return { ...week, [weekday]: [...day, row] }
}

export function updateRange(
  week: WeekDraft,
  weekday: number,
  id: string,
  patch: Partial<Pick<DayRange, "startMinute" | "endMinute">>,
): WeekDraft {
  const day = week[weekday as IsoWeekday]
  if (!day) return week
  return { ...week, [weekday]: day.map((r) => (r.id === id ? { ...r, ...patch } : r)) }
}

export function removeRange(week: WeekDraft, weekday: number, id: string): WeekDraft {
  const day = week[weekday as IsoWeekday]
  if (!day) return week
  return { ...week, [weekday]: day.filter((r) => r.id !== id) }
}

/** "Saved as two windows: Monday 22:00 to 24:00 and Tuesday 00:00 to 02:00." or null. */
export function splitNotice(weekday: number, range: DayRange): string | null {
  if (!crossesMidnight(range)) return null
  const next = nextDay(weekday)
  return (
    `Saved as two windows: ${dayLabel(weekday)} ${formatMinute(range.startMinute)} to ${formatMinute(MINUTES_PER_DAY)} ` +
    `and ${dayLabel(next)} ${formatMinute(0)} to ${formatMinute(range.endMinute)}.`
  )
}

// ── Validation ──────────────────────────────────────────────────────────────

export type RangeProblemKind = "step" | "empty" | "bounds" | "overlap"

export interface RangeProblem {
  rangeId: string
  weekday: IsoWeekday
  kind: RangeProblemKind
  /** One sentence that says what to change. */
  message: string
}

export interface WeekValidation {
  problems: RangeProblem[]
  /** Stored rules the week would save as, after the midnight split. */
  ruleCount: number
  /** More rules than the server accepts. */
  tooMany: boolean
}

const MESSAGES: Record<RangeProblemKind, string> = {
  step: "Use times on the quarter hour, such as 09:00 or 09:15.",
  empty: "The start and the end are the same time. Pick an end after the start.",
  bounds: "Pick times between 00:00 and 24:00.",
  overlap: "This time overlaps another one on the same day. Change a time so they only touch.",
}

interface Piece {
  rangeId: string
  weekday: IsoWeekday
  startMinute: number
  endMinute: number
}

export function validateWeek(week: WeekDraft): WeekValidation {
  const problems: RangeProblem[] = []
  const flagged = new Set<string>()
  const pieces: Piece[] = []

  const flag = (range: DayRange, weekday: IsoWeekday, kind: RangeProblemKind) => {
    const key = `${range.id}:${kind}`
    if (flagged.has(key)) return
    flagged.add(key)
    problems.push({ rangeId: range.id, weekday, kind, message: MESSAGES[kind] })
  }

  for (const weekday of ISO_DAYS) {
    for (const range of week[weekday]) {
      const { startMinute: start, endMinute: end } = range
      if (
        !Number.isInteger(start) ||
        !Number.isInteger(end) ||
        start < 0 ||
        start > MINUTES_PER_DAY - STEP_MINUTES ||
        end < 0 ||
        end > MINUTES_PER_DAY ||
        // End at 00:00 is written 24:00; a stored rule cannot end at minute 0.
        end === 0
      ) {
        flag(range, weekday, "bounds")
        continue
      }
      if (start % STEP_MINUTES !== 0 || end % STEP_MINUTES !== 0) {
        flag(range, weekday, "step")
        continue
      }
      if (start === end) {
        flag(range, weekday, "empty")
        continue
      }
      for (const rule of splitRange(weekday, range)) {
        pieces.push({
          rangeId: range.id,
          weekday: rule.isoWeekday as IsoWeekday,
          startMinute: rule.startMinute,
          endMinute: rule.endMinute,
        })
      }
    }
  }

  // Overlap: compare each piece with the piece that reaches furthest so far on its day,
  // so a long window is checked against every later one, not only its neighbour.
  const ranges = new Map<string, { range: DayRange; weekday: IsoWeekday }>()
  for (const weekday of ISO_DAYS) for (const range of week[weekday]) ranges.set(range.id, { range, weekday })

  pieces.sort((a, b) => a.weekday - b.weekday || a.startMinute - b.startMinute || a.endMinute - b.endMinute)
  let reach: Piece | null = null
  for (const piece of pieces) {
    if (reach === null || reach.weekday !== piece.weekday) {
      reach = piece
      continue
    }
    if (piece.startMinute < reach.endMinute) {
      for (const hit of [piece, reach]) {
        const entry = ranges.get(hit.rangeId)
        if (entry) flag(entry.range, entry.weekday, "overlap")
      }
    }
    if (piece.endMinute > reach.endMinute) reach = piece
  }

  const ruleCount = pieces.length
  return { problems, ruleCount, tooMany: ruleCount > MAX_RULES }
}
