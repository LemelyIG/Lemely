/*
 * C-19 · pure grouping and labelling of bookable slots (SPEC §d, §0 "Times",
 * §i.4).
 *
 * Every tutoring screen shows times in the TUTOR's zone with its label, for
 * every viewer ("Thu 30 Oct · 17:00–18:00 Cairo time"), because a session
 * happens where the tutor is. So a slot belongs to the day it falls on in that
 * zone: a slot at 22:30Z belongs to the next Cairo day, whatever the viewer's
 * device clock says.
 *
 * The zone comes from the API (`Slots.zone`, an IANA name); this module owns no
 * zone of its own. `Intl` is asked only for the zone's calendar fields and UTC
 * offset as numbers. The weekday and month names are produced here from those
 * numbers, so the labels do not move with an ICU build ("Sept" against "Sep").
 *
 * The hour the clocks go back is repeated in the zone's wall time. The backend
 * offers no slot whose start or end label is ambiguous (SPEC §i.4); this module
 * still refuses to print two different instants under one label. Where a day's
 * labels clash, every clashing label carries its UTC offset ("23:00 (UTC+3)").
 *
 * Calendar-day stepping (`windowDays`) is plain date arithmetic on day keys, so
 * a 23- or 25-hour day can neither skip nor repeat a day.
 */

import type { Slot } from "@/lib/tutoringTypes"

export interface SlotChoice {
  startsAt: string
  endsAt: string
  /** The start as the radio shows it: "17:00", or "23:00 (UTC+3)" in a repeated hour. */
  label: string
  /** "17:00–18:00". */
  rangeLabel: string
  /** "Thu 30 Oct · 17:00–18:00 Cairo time". */
  fullLabel: string
}

export interface SlotDay {
  /** "YYYY-MM-DD" in the tutor's zone. */
  dayKey: string
  /** "Thu 30 Oct". */
  chipLabel: string
  slots: SlotChoice[]
}

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"] as const
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"] as const

interface WallClock {
  year: number
  month: number
  day: number
  hour: number
  minute: number
  /** "UTC+3", "UTC+5:30", "UTC". */
  offset: string
  ms: number
}

const formatters = new Map<string, Intl.DateTimeFormat>()

function formatterFor(zone: string): Intl.DateTimeFormat {
  let formatter = formatters.get(zone)
  if (!formatter) {
    formatter = new Intl.DateTimeFormat("en-US", {
      timeZone: zone,
      year: "numeric",
      month: "numeric",
      day: "numeric",
      hour: "numeric",
      minute: "numeric",
      hourCycle: "h23",
      timeZoneName: "longOffset",
    })
    formatters.set(zone, formatter)
  }
  return formatter
}

/** "GMT+03:00" becomes "UTC+3"; "GMT" becomes "UTC". */
function offsetLabel(raw: string): string {
  const match = /^GMT(?:([+-])(\d{2}):(\d{2}))?$/.exec(raw)
  if (!match || !match[1]) return "UTC"
  const hours = String(Number(match[2]))
  const minutes = match[3] === "00" ? "" : `:${match[3]}`
  return `UTC${match[1]}${hours}${minutes}`
}

function wallClock(iso: string, zone: string): WallClock | null {
  const date = new Date(iso)
  const ms = date.getTime()
  if (Number.isNaN(ms)) return null
  let parts: Intl.DateTimeFormatPart[]
  try {
    parts = formatterFor(zone).formatToParts(date)
  } catch {
    return null
  }
  const num = (type: string): number => Number(parts.find((p) => p.type === type)?.value ?? "0")
  return {
    year: num("year"),
    month: num("month"),
    day: num("day"),
    hour: num("hour"),
    minute: num("minute"),
    offset: offsetLabel(parts.find((p) => p.type === "timeZoneName")?.value ?? "GMT"),
    ms,
  }
}

const two = (n: number): string => String(n).padStart(2, "0")

function dayKeyOf(year: number, month: number, day: number): string {
  return `${year}-${two(month)}-${two(day)}`
}

function chipLabelOf(year: number, month: number, day: number): string {
  const weekday = WEEKDAYS[new Date(Date.UTC(year, month - 1, day)).getUTCDay()]
  return `${weekday} ${day} ${MONTHS[month - 1]}`
}

const clock = (w: WallClock): string => `${two(w.hour)}:${two(w.minute)}`

/**
 * Group slots by the tutor's calendar day, oldest first, each day's slots in
 * time order. A slot that does not parse is left out rather than guessed at.
 */
export function groupSlotsByDay(slots: readonly Slot[], zone: string, zoneLabel: string): SlotDay[] {
  const items = slots
    .map((slot) => ({ slot, start: wallClock(slot.startsAt, zone), end: wallClock(slot.endsAt, zone) }))
    .filter((item): item is { slot: Slot; start: WallClock; end: WallClock } => item.start !== null && item.end !== null)
    .sort((a, b) => a.start.ms - b.start.ms)

  const byDay = new Map<string, typeof items>()
  for (const item of items) {
    const key = dayKeyOf(item.start.year, item.start.month, item.start.day)
    const bucket = byDay.get(key)
    if (bucket) bucket.push(item)
    else byDay.set(key, [item])
  }

  const days: SlotDay[] = []
  for (const [dayKey, bucket] of byDay) {
    // A wall-clock label that stands for more than one instant on this day.
    const instants = new Map<string, Set<number>>()
    for (const { start, end } of bucket) {
      for (const w of [start, end]) {
        const set = instants.get(clock(w)) ?? new Set<number>()
        set.add(w.ms)
        instants.set(clock(w), set)
      }
    }
    const label = (w: WallClock): string =>
      (instants.get(clock(w))?.size ?? 0) > 1 ? `${clock(w)} (${w.offset})` : clock(w)

    const first = bucket[0].start
    const chipLabel = chipLabelOf(first.year, first.month, first.day)
    days.push({
      dayKey,
      chipLabel,
      slots: bucket.map(({ slot, start, end }) => {
        const rangeLabel = `${label(start)}–${label(end)}`
        return {
          startsAt: slot.startsAt,
          endsAt: slot.endsAt,
          label: label(start),
          rangeLabel,
          fullLabel: `${chipLabel} · ${rangeLabel} ${zoneLabel}`,
        }
      }),
    })
  }
  return days
}

/**
 * Every calendar day of the window `[windowStart, windowEnd)` in the tutor's
 * zone, including days with no slot, so the picker can say so.
 */
export function windowDays(
  windowStart: string,
  windowEnd: string,
  zone: string,
): { dayKey: string; chipLabel: string }[] {
  const start = wallClock(windowStart, zone)
  const endInstant = new Date(windowEnd).getTime() - 1
  const end = Number.isNaN(endInstant) ? null : wallClock(new Date(endInstant).toISOString(), zone)
  if (!start || !end) return []

  const last = Date.UTC(end.year, end.month - 1, end.day)
  const days: { dayKey: string; chipLabel: string }[] = []
  // 62 is a guard against a malformed window, not a product limit (the API caps it at 28 days).
  for (let cursor = Date.UTC(start.year, start.month - 1, start.day), i = 0; cursor <= last && i < 62; i++) {
    const d = new Date(cursor)
    const y = d.getUTCFullYear()
    const m = d.getUTCMonth() + 1
    const day = d.getUTCDate()
    days.push({ dayKey: dayKeyOf(y, m, day), chipLabel: chipLabelOf(y, m, day) })
    cursor = Date.UTC(y, m - 1, day + 1)
  }
  return days
}

/** The count line under a day chip. Words, so the chip never relies on colour. */
export function dayChipSummary(count: number): string {
  if (count <= 0) return "No times"
  return `${count} ${count === 1 ? "time" : "times"}`
}

/** "Thu 30 Oct · 17:00–18:00 Cairo time", for a booking's start and end. */
export function formatSlotRange(startsAt: string, endsAt: string, zone: string, zoneLabel: string): string {
  const start = wallClock(startsAt, zone)
  const end = wallClock(endsAt, zone)
  if (!start || !end) return ""
  return `${chipLabelOf(start.year, start.month, start.day)} · ${clock(start)}–${clock(end)} ${zoneLabel}`
}

/** "Thu 30 Oct · 17:05 Cairo time", for a single instant such as a note's time. */
export function formatTutorInstant(iso: string, zone: string, zoneLabel: string): string {
  const w = wallClock(iso, zone)
  if (!w) return ""
  return `${chipLabelOf(w.year, w.month, w.day)} · ${clock(w)} ${zoneLabel}`
}
