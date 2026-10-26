import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"
import {
  BOOKING_STATUS,
  EFFECTIVE_STATES,
  bookingStatusAriaLabel,
  bookingStatusOf,
} from "@/lib/tutoring/bookingStatus"
import { stripComments } from "./support/jsxSource"

/*
 * C-20 (SPEC §d): "icon + text per effective state; never colour alone".
 *
 * The states are read out of SPEC §a.3, not written out a second time: the four
 * derived read-time states come from the "Derived read-time states" table, the
 * stored ones from the `bookingstate` enum in §a.1. Their union is the set of
 * effective states, and its size is asserted so a parse that found nothing
 * cannot pass.
 */

const SPEC = readFileSync(
  join(import.meta.dirname, "..", "..", "..", "docs", "tutoring", "SPEC.md"),
  "utf8",
)

function specStoredStates(): string[] {
  const row = SPEC.split("\n").find((line) => line.startsWith("| `bookingstate` |")) ?? ""
  const cell = row.split("|")[2] ?? ""
  return [...cell.matchAll(/`([a-z_]+)`/g)].map((m) => m[1])
}

function specDerivedStates(): string[] {
  const start = SPEC.indexOf("Derived read-time states")
  const end = SPEC.indexOf("Transitions are compare-and-set", start)
  expect(start).toBeGreaterThan(-1)
  expect(end).toBeGreaterThan(start)
  const names: string[] = []
  for (const line of SPEC.slice(start, end).split("\n")) {
    const match = /^\| `([a-z_]+)`/.exec(line)
    if (match) names.push(match[1])
  }
  return names
}

const stored = specStoredStates()
const derived = specDerivedStates()
const SPEC_STATES = [...new Set([...stored, ...derived])].sort()

describe("effective states parsed from SPEC section a.3", () => {
  it("finds the seven stored states and the four derived ones, eight in all", () => {
    expect(stored).toHaveLength(7)
    expect(derived.sort()).toEqual(["accepted", "awaiting_outcome", "expired", "requested"])
    expect(SPEC_STATES).toHaveLength(8)
  })

  it("the component knows exactly those states", () => {
    expect([...EFFECTIVE_STATES].sort()).toEqual(SPEC_STATES)
    expect(Object.keys(BOOKING_STATUS).sort()).toEqual(SPEC_STATES)
  })
})

describe("every effective state has an icon and text", () => {
  for (const state of SPEC_STATES) {
    it(`${state}: icon, label and tone`, () => {
      const status = bookingStatusOf(state as (typeof EFFECTIVE_STATES)[number])
      expect(status.icon.length).toBeGreaterThan(0)
      expect(status.label.trim().length).toBeGreaterThan(0)
      expect(status.tone.length).toBeGreaterThan(0)
    })
  }

  it("no two states share a label or an icon, so colour is never the only difference", () => {
    const labels = SPEC_STATES.map((s) => BOOKING_STATUS[s as keyof typeof BOOKING_STATUS].label)
    const icons = SPEC_STATES.map((s) => BOOKING_STATUS[s as keyof typeof BOOKING_STATUS].icon)
    expect(new Set(labels).size).toBe(SPEC_STATES.length)
    expect(new Set(icons).size).toBe(SPEC_STATES.length)
  })

  it("aria-label is a phrase that names the state", () => {
    expect(bookingStatusAriaLabel("awaiting_outcome")).toBe("Session status: Awaiting outcome")
    expect(bookingStatusAriaLabel("no_show")).toBe("Session status: No-show")
  })

  it("an expired request reads as a calendar date that passed, not as a running clock", () => {
    expect(BOOKING_STATUS.expired.icon).toBe("CalendarX")
    expect(Object.values(BOOKING_STATUS).map((s) => s.icon)).not.toContain("ClockCountdown")
  })

  it("labels avoid the words the tutoring copy rule bans", () => {
    for (const state of SPEC_STATES) {
      const label = BOOKING_STATUS[state as keyof typeof BOOKING_STATUS].label
      expect(label).not.toMatch(/\b(?:improvements?|verified)\b/i)
    }
  })
})

describe("component source (C-20)", () => {
  const readRaw = () => readFileSync(
    join(import.meta.dirname, "..", "..", "src", "components", "ui", "booking-status.tsx"),
    "utf8",
  )
  // Comments are blanked: the file's header prose quotes the very strings checked here.
  const read = () => stripComments(readRaw())

  it("renders the icon and the label together, with the icon hidden from AT", () => {
    expect(read()).toContain("aria-hidden")
    expect(read()).toContain("status.label")
    expect(read()).toContain("ICONS[")
  })

  it("maps every icon name the pure module uses", () => {
    const names = new Set(Object.values(BOOKING_STATUS).map((s) => s.icon))
    for (const name of names) expect(read()).toContain(`${name}:`)
    expect(names.size).toBe(SPEC_STATES.length)
    expect(read()).not.toContain("ClockCountdown")
  })
})
