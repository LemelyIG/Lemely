import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"
import { tutoringQueryString } from "@/lib/hooks/useTutoringApi"
import {
  COUNTING_NOTICE_STUDENT,
  DIRECTORY_EMPTY_HEADING,
  DIRECTORY_INTRO,
  DOCUMENTS_SEEN_DISCLOSURE,
  NO_REVIEWS_LINE,
  DIRECTORY_SIGN_IN_LINE,
  EMPTY_FILTERS,
  GRADE_RANKING_NOTE,
  MODE_OPTIONS,
  PLATFORM_EMPTY_HEADING,
  RATING_OPTIONS,
  SHARE_EXPLAINER,
  SHARE_PARENTS_LINE,
  TIME_OF_DAY_OPTIONS,
  activeFilterCount,
  appendUnique,
  availabilityRows,
  countingNotice,
  directoryQuery,
  filtersFromSearchParams,
  filtersToSearchParams,
  hasActiveFilters,
  listedSinceLabel,
  minuteLabel,
  resultsCaption,
  slotWindow,
  todayInZone,
  type DirectoryFilterState,
} from "@/lib/tutoring/discovery"

/*
 * T22: filter state <-> query params, and the fixed copy of G-16, S-33, S-34
 * and S-35. Every expected sentence and range is read out of SPEC §d / §b.2
 * as text (never written a second time here), so a wording change has to be
 * made in the SPEC first.
 */

const SPEC = readFileSync(
  join(import.meta.dirname, "..", "..", "..", "docs", "tutoring", "SPEC.md"),
  "utf8",
)

/** The text of SPEC section `heading` (a `**G-16 ...**` style line) up to the next screen heading. */
function screen(id: string): string {
  const start = SPEC.indexOf(`**${id} ·`)
  if (start < 0) throw new Error(`SPEC screen ${id} not found`)
  const next = SPEC.indexOf("\n\n**", start + 5)
  const end = next < 0 ? SPEC.length : next
  return SPEC.slice(start, end)
}

/** The first double-quoted sentence after `anchor` in `text`. */
function quotedAfter(text: string, anchor: string): string {
  const from = text.indexOf(anchor)
  if (from < 0) throw new Error(`anchor not found: ${anchor}`)
  const open = text.indexOf('"', from + anchor.length)
  const close = text.indexOf('"', open + 1)
  if (open < 0 || close < 0) throw new Error(`no quoted text after: ${anchor}`)
  return text.slice(open + 1, close)
}

const params = (query: string): URLSearchParams => new URLSearchParams(query)

describe("filters <-> query params", () => {
  it("reads every filter of the member directory from the address", () => {
    const filters = filtersFromSearchParams(
      params("subject=0580&mode=virtual&mode=in_person&area=maadi&minRating=4.5&day=2&day=5&timeOfDay=evening"),
      "member",
    )
    expect(filters).toEqual({
      subject: "0580",
      modes: ["virtual", "in_person"],
      area: "maadi",
      minRating: 4.5,
      days: [2, 5],
      timesOfDay: ["evening"],
    } satisfies DirectoryFilterState)
  })

  it("round-trips: write then read gives the same state, and the address is stable", () => {
    const state: DirectoryFilterState = {
      subject: "0625",
      modes: ["other", "virtual"],
      area: "zamalek",
      minRating: 3.5,
      days: [7, 1, 3],
      timesOfDay: ["afternoon", "morning"],
    }
    const written = filtersToSearchParams(state, "member")
    const back = filtersFromSearchParams(written, "member")
    // Order is canonical, not the order the reader clicked in.
    expect(back).toEqual({
      ...state,
      modes: ["virtual", "other"],
      days: [1, 3, 7],
      timesOfDay: ["morning", "afternoon"],
    })
    expect(filtersToSearchParams(back, "member").toString()).toBe(written.toString())
  })

  it("an empty state writes an empty address, and an empty address reads as the empty state", () => {
    expect(filtersToSearchParams(EMPTY_FILTERS, "member").toString()).toBe("")
    expect(filtersFromSearchParams(params(""), "public")).toEqual(EMPTY_FILTERS)
  })

  it("ignores values the API would refuse or that are not options", () => {
    const filters = filtersFromSearchParams(
      params("mode=virtual&mode=teleport&mode=virtual&minRating=2.2&day=0&day=8&day=x&day=3&timeOfDay=noon&timeOfDay=morning"),
      "member",
    )
    expect(filters.modes).toEqual(["virtual"])
    expect(filters.minRating).toBeNull()
    expect(filters.days).toEqual([3])
    expect(filters.timesOfDay).toEqual(["morning"])
    expect(filtersFromSearchParams(params("minRating=abc"), "member").minRating).toBeNull()
    expect(filtersFromSearchParams(params("minRating=5.5"), "member").minRating).toBeNull()
  })

  it("the public directory has no availability filter (P1, row 5b)", () => {
    const filters = filtersFromSearchParams(params("subject=0580&day=2&timeOfDay=evening"), "public")
    expect(filters.days).toEqual([])
    expect(filters.timesOfDay).toEqual([])
    const written = filtersToSearchParams(
      { ...EMPTY_FILTERS, subject: "0580", days: [2], timesOfDay: ["evening"] },
      "public",
    )
    expect(written.toString()).toBe("subject=0580")
  })

  it("builds the exact request each audience may send", () => {
    const state: DirectoryFilterState = {
      subject: "0580",
      modes: ["virtual", "in_person"],
      area: "maadi",
      minRating: 4,
      days: [2],
      timesOfDay: ["evening"],
    }
    expect(directoryQuery(state, "public")).toEqual({
      subject: "0580",
      mode: ["virtual", "in_person"],
      area: "maadi",
      minRating: 4,
    })
    expect(directoryQuery(state, "member", "abc")).toEqual({
      subject: "0580",
      mode: ["virtual", "in_person"],
      area: "maadi",
      minRating: 4,
      day: [2],
      timeOfDay: ["evening"],
      cursor: "abc",
    })
    // Nothing set sends nothing: the query string is empty.
    expect(tutoringQueryString(directoryQuery(EMPTY_FILTERS, "member"))).toBe("")
    expect(tutoringQueryString(directoryQuery(state, "member"))).toBe(
      "?subject=0580&mode=virtual&mode=in_person&area=maadi&minRating=4&day=2&timeOfDay=evening",
    )
  })

  it("counts and detects active filters per audience", () => {
    const state: DirectoryFilterState = { ...EMPTY_FILTERS, subject: "0580", days: [1, 2], timesOfDay: ["morning"] }
    expect(hasActiveFilters(EMPTY_FILTERS, "member")).toBe(false)
    expect(hasActiveFilters(state, "member")).toBe(true)
    expect(activeFilterCount(state, "member")).toBe(2 + 1 + 1)
    // A public reader cannot set availability, so it is not counted for them.
    expect(activeFilterCount(state, "public")).toBe(1)
  })
})

describe("the options come from the API's rules", () => {
  it("offers only minimum ratings P1 accepts (1.0 to 5.0 in steps of 0.5)", () => {
    const row = SPEC.split("\n").find((line) => line.startsWith("| P1 |"))
    expect(row).toBeDefined()
    expect(row).toContain("`minRating?` (1.0–5.0, step 0.5)")
    expect(RATING_OPTIONS.length).toBeGreaterThanOrEqual(3)
    for (const value of RATING_OPTIONS) {
      expect(value).toBeGreaterThanOrEqual(1)
      expect(value).toBeLessThanOrEqual(5)
      expect((value * 2) % 1).toBe(0)
    }
  })

  it("labels the time-of-day buckets with the SPEC's hours", () => {
    const line = SPEC.split("\n").find((l) => l.startsWith("Time-of-day buckets"))
    expect(line).toBeDefined()
    const parsed = [...(line ?? "").matchAll(/(morning|afternoon|evening) (\d\d:\d\d)–(\d\d:\d\d)/g)]
    expect(parsed.map((m) => m[1])).toEqual(TIME_OF_DAY_OPTIONS.map((o) => o.value))
    for (const [, name, from, to] of parsed) {
      const option = TIME_OF_DAY_OPTIONS.find((o) => o.value === name)
      expect(option?.hours).toBe(`${from}–${to}`)
    }
  })

  it("has one option per way of meeting the API knows", () => {
    expect(MODE_OPTIONS.map((m) => m.value)).toEqual(["virtual", "in_person", "other"])
  })
})

describe("fixed copy, parsed from the SPEC", () => {
  it("G-16 intro, empty states and sign-in line", () => {
    const g16 = screen("G-16")
    expect(DIRECTORY_INTRO).toBe(quotedAfter(g16, "Intro ("))
    expect(DIRECTORY_SIGN_IN_LINE).toBe(quotedAfter(g16, "Load more\". "))
    expect(DIRECTORY_EMPTY_HEADING).toBe(quotedAfter(g16, "Empty: "))
    expect(PLATFORM_EMPTY_HEADING).toBe(quotedAfter(g16, "Empty platform: "))
  })

  it("S-33 ranking disclosure", () => {
    expect(GRADE_RANKING_NOTE).toBe(quotedAfter(screen("S-33"), "info disclosure: "))
  })

  it("S-34 results caption, with the two windows filled in", () => {
    const template = quotedAfter(screen("S-34"), "caption under both: ")
    expect(template).toContain("{duringWindowDays}")
    expect(template).toContain("{beforeLookbackDays}")
    expect(resultsCaption(90, 120)).toBe(
      template.replace("{duringWindowDays}", "90").replace("{beforeLookbackDays}", "120"),
    )
    // It does not claim the tutor caused anything, and it says the marking is automatic.
    expect(resultsCaption(90, 120)).toContain("doesn't show what the tutor caused")
    expect(resultsCaption(90, 120)).toContain("automatic marking")
  })

  it("S-34 documents-seen disclosure and the empty reviews line", () => {
    const s34 = screen("S-34")
    expect(DOCUMENTS_SEEN_DISCLOSURE).toBe(quotedAfter(s34, "(disclosure: "))
    expect(NO_REVIEWS_LINE).toBe(quotedAfter(s34, "No reviews: "))
  })

  it("S-35 counting notice, for the student and for a parent booking for a child", () => {
    expect(COUNTING_NOTICE_STUDENT).toBe(quotedAfter(screen("S-35"), "**Counting notice** (row 8b): "))
    expect(countingNotice("student")).toBe(COUNTING_NOTICE_STUDENT)
    const parent = countingNotice("parent", "Maya")
    expect(parent).toContain("Maya")
    expect(parent).not.toContain("your grades")
    expect(parent).not.toContain("You can opt out")
  })

  it("the share-progress explainer is S-38's, word for word", () => {
    const s38 = screen("S-38")
    expect(SHARE_EXPLAINER).toBe(quotedAfter(s38, "Explainer (F29): "))
    expect(SHARE_PARENTS_LINE).toBe(quotedAfter(s38, SHARE_EXPLAINER + '" '))
  })
})

describe("the lists on the page", () => {
  it("appends a page without repeating a tutor that moved between pages", () => {
    const card = (tutorId: string) => ({ tutorId })
    const merged = appendUnique([card("a"), card("b")], [card("b"), card("c")], (c) => c.tutorId)
    expect(merged.map((c) => c.tutorId)).toEqual(["a", "b", "c"])
  })

  it("writes 'Listed since' as a month and year, and says nothing before a first approval", () => {
    expect(listedSinceLabel("2026-03")).toBe("Mar 2026")
    expect(listedSinceLabel("2025-12")).toBe("Dec 2025")
    expect(listedSinceLabel(null)).toBeNull()
    expect(listedSinceLabel("not-a-month")).toBeNull()
    expect(listedSinceLabel("2026-13")).toBeNull()
  })

  it("lays a week of availability out as seven rows with ranges, and lists a free day as no times", () => {
    const rows = availabilityRows([
      { isoWeekday: 3, startMinute: 17 * 60, endMinute: 18 * 60 + 30 },
      { isoWeekday: 1, startMinute: 9 * 60, endMinute: 12 * 60 },
      { isoWeekday: 1, startMinute: 15 * 60 + 15, endMinute: 16 * 60 },
    ])
    expect(rows.map((r) => r.isoWeekday)).toEqual([1, 2, 3, 4, 5, 6, 7])
    expect(rows[0].ranges).toEqual(["09:00–12:00", "15:15–16:00"])
    expect(rows[2].ranges).toEqual(["17:00–18:30"])
    expect(rows[1].ranges).toEqual([])
    expect(rows[0].dayLabel).toBe("Monday")
    expect(minuteLabel(0)).toBe("00:00")
    expect(minuteLabel(24 * 60)).toBe("24:00")
  })
})

describe("the booking window", () => {
  it("asks for 14 days, then up to 28 when the reader wants later dates (SP5)", () => {
    expect(slotWindow(false)).toBe(14)
    expect(slotWindow(true)).toBe(28)
    const row = SPEC.split("\n").find((line) => line.startsWith("| SP5 |")) ?? ""
    expect(row).toContain("`days` (1–28, default 14; `from + days ≤ today + 28`)")
  })

  it("starts the window at today's date in the TUTOR's zone, not the browser's", () => {
    // 22:30 UTC on 25 Oct 2026 is already 26 Oct in Cairo (UTC+3 until the clocks go back on the 29th).
    const now = new Date("2026-10-25T22:30:00Z")
    expect(todayInZone("Africa/Cairo", now)).toBe("2026-10-26")
    expect(todayInZone("UTC", now)).toBe("2026-10-25")
    expect(todayInZone("America/Los_Angeles", now)).toBe("2026-10-25")
  })

  it("falls back to UTC for a zone name the runtime does not know, rather than throwing", () => {
    expect(todayInZone("Not/AZone", new Date("2026-10-25T22:30:00Z"))).toBe("2026-10-25")
  })
})
