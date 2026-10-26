import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"
import {
  dayChipSummary,
  formatSlotRange,
  formatTutorInstant,
  groupSlotsByDay,
  windowDays,
} from "@/lib/tutoring/slotGroups"
import type { Slot } from "@/lib/tutoringTypes"
import { stripComments } from "./support/jsxSource"

/*
 * C-19 (SPEC §d): slots are grouped by the TUTOR's day, in the tutor's zone,
 * whatever the viewer's device says (SPEC §0 "Times"). Fixtures sit on the
 * night Egypt's clocks go back (Thu 29 Oct 2026, 24:00 -> 23:00), because that
 * is where "no ambiguous repeated hour" is decided (SPEC §i.4).
 */

const ZONE = "Africa/Cairo"
const LABEL = "Cairo time"

function slot(startsAt: string, endsAt: string): Slot {
  return { startsAt, endsAt }
}

describe("groupSlotsByDay", () => {
  it("groups by the tutor's calendar day, not the UTC day", () => {
    // 22:30Z on Fri 30 Oct is 00:30 on Sat 31 Oct in Cairo (UTC+2 after the change).
    const days = groupSlotsByDay(
      [
        slot("2026-10-30T10:00:00Z", "2026-10-30T11:00:00Z"),
        slot("2026-10-30T22:30:00Z", "2026-10-30T23:30:00Z"),
      ],
      ZONE,
      LABEL,
    )
    expect(days.map((d) => d.dayKey)).toEqual(["2026-10-30", "2026-10-31"])
    expect(days[0].chipLabel).toBe("Fri 30 Oct")
    expect(days[1].chipLabel).toBe("Sat 31 Oct")
    expect(days[1].slots[0].label).toBe("00:30")
  })

  it("orders days and the slots inside a day by time, whatever order they arrive in", () => {
    const days = groupSlotsByDay(
      [
        slot("2026-11-02T15:00:00Z", "2026-11-02T16:00:00Z"),
        slot("2026-11-02T09:00:00Z", "2026-11-02T10:00:00Z"),
        slot("2026-11-01T09:00:00Z", "2026-11-01T10:00:00Z"),
      ],
      ZONE,
      LABEL,
    )
    expect(days.map((d) => d.dayKey)).toEqual(["2026-11-01", "2026-11-02"])
    expect(days[1].slots.map((s) => s.label)).toEqual(["11:00", "17:00"])
  })

  it("labels a slot as a range in the tutor's zone with the zone label, as in the SPEC", () => {
    const [day] = groupSlotsByDay([slot("2026-10-30T15:00:00Z", "2026-10-30T16:00:00Z")], ZONE, LABEL)
    expect(day.slots[0].rangeLabel).toBe("17:00–18:00")
    expect(day.slots[0].fullLabel).toBe("Fri 30 Oct · 17:00–18:00 Cairo time")
  })

  it("matches the time format the SPEC prescribes for every tutoring screen", () => {
    const spec = readFileSync(
      join(import.meta.dirname, "..", "..", "..", "docs", "tutoring", "SPEC.md"),
      "utf8",
    )
    expect(spec).toContain(`"Thu 30 Oct · 17:00–18:00 Cairo time"`)
    // Thu 30 Oct 2025 is a Thursday, and Cairo is still on summer time until that night (UTC+3).
    expect(formatSlotRange("2025-10-30T14:00:00Z", "2025-10-30T15:00:00Z", ZONE, LABEL)).toBe(
      "Thu 30 Oct · 17:00–18:00 Cairo time",
    )
  })

  it("gives the two 23:00 starts of the repeated hour distinct labels", () => {
    // 20:00Z is 23:00 at UTC+3 and 21:00Z is 23:00 at UTC+2, on the same Cairo day.
    const days = groupSlotsByDay(
      [
        slot("2026-10-29T20:00:00Z", "2026-10-29T21:00:00Z"),
        slot("2026-10-29T21:00:00Z", "2026-10-29T22:00:00Z"),
      ],
      ZONE,
      LABEL,
    )
    expect(days).toHaveLength(1)
    const [first, second] = days[0].slots
    expect(first.label).not.toBe(second.label)
    expect(first.label).toBe("23:00 (UTC+3)")
    expect(second.label).toBe("23:00 (UTC+2)")
    // The first slot starts and ends on the same wall-clock time, so its end carries the offset too.
    expect(first.rangeLabel).toBe("23:00 (UTC+3)–23:00 (UTC+2)")
  })

  it("adds no offset to a day with no repeated hour", () => {
    const days = groupSlotsByDay(
      [
        slot("2026-10-28T08:00:00Z", "2026-10-28T09:00:00Z"),
        slot("2026-10-28T12:00:00Z", "2026-10-28T13:00:00Z"),
      ],
      ZONE,
      LABEL,
    )
    for (const s of days[0].slots) expect(s.label + s.rangeLabel).not.toContain("UTC")
  })

  it("returns nothing for no slots", () => {
    expect(groupSlotsByDay([], ZONE, LABEL)).toEqual([])
  })
})

describe("windowDays", () => {
  it("lists every tutor-zone day of the window, including days with no slot", () => {
    const days = windowDays("2026-10-27T22:00:00Z", "2026-10-30T22:00:00Z", ZONE)
    // The start is 01:00 on 28 Oct in Cairo; the end instant is midnight at the start of 31 Oct
    // and excluded, so the window is 28, 29 and 30 Oct.
    expect(days.map((d) => d.dayKey)).toEqual(["2026-10-28", "2026-10-29", "2026-10-30"])
    expect(days.map((d) => d.chipLabel)).toEqual(["Wed 28 Oct", "Thu 29 Oct", "Fri 30 Oct"])
  })

  it("steps over the clock change without skipping or repeating a day", () => {
    const keys = windowDays("2026-10-26T21:00:00Z", "2026-11-02T22:00:00Z", ZONE).map((d) => d.dayKey)
    expect(keys).toEqual([
      "2026-10-27",
      "2026-10-28",
      "2026-10-29",
      "2026-10-30",
      "2026-10-31",
      "2026-11-01",
      "2026-11-02",
    ])
  })
})

describe("dayChipSummary", () => {
  it("says how many times a day has, in words, never colour alone", () => {
    expect(dayChipSummary(0)).toBe("No times")
    expect(dayChipSummary(1)).toBe("1 time")
    expect(dayChipSummary(5)).toBe("5 times")
  })
})

describe("formatTutorInstant", () => {
  it("formats a note or booking instant in the tutor's zone, with the label", () => {
    expect(formatTutorInstant("2026-10-30T15:05:00Z", ZONE, LABEL)).toBe(
      "Fri 30 Oct · 17:05 Cairo time",
    )
  })
})

describe("component source (C-19)", () => {
  const readRaw = () => readFileSync(
    join(import.meta.dirname, "..", "..", "src", "components", "ui", "slot-picker.tsx"),
    "utf8",
  )
  // Comments are blanked: the file's header prose quotes the very strings checked here.
  const read = () => stripComments(readRaw())

  it("uses native radios for the days and the times, so arrow keys work inside each group", () => {
    expect(read().match(/type="radio"/g)?.length).toBeGreaterThanOrEqual(2)
    expect(read()).toContain("<fieldset")
    expect(read()).toContain("<legend")
  })

  it("shows the zone label and a per-day empty line", () => {
    expect(read()).toContain("zoneLabel")
    expect(read()).toContain("No times on this day.")
  })

  it("gets its grouping from the pure module and does no date arithmetic of its own", () => {
    expect(read()).toContain("groupSlotsByDay")
    expect(read()).not.toContain("new Date(")
    expect(read()).not.toContain("Intl.")
  })
})
