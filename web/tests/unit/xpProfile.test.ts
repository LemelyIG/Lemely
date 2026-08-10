import { describe, expect, it } from "vitest"
import {
  calendarDays,
  fillCalendar,
  levelProgress,
  sourceLabel,
} from "@/portals/student/screens/Profile"
import type { XpProfile } from "@/lib/xpTypes"

/*
 * S-31's pure logic (P5.8 chunk D).
 *
 * The two things worth pinning hard are the calendar's absent/zero handling
 * and the fact that the level curve is never re-derived here. Both are places
 * the screen could silently disagree with the backend about a number a student
 * is being motivated by.
 */

function profile(overrides: Partial<XpProfile> = {}): XpProfile {
  return {
    totalXp: 250,
    level: 1,
    levelStartXp: 100,
    nextLevelXp: 400,
    streak: {
      current: 3,
      longest: 9,
      lastActiveOn: "2026-08-10",
      freezesAvailable: 1,
    },
    week: {
      start: "2026-08-10",
      end: "2026-08-16",
      total: 60,
      bySource: [
        { source: "paper_corrected", xp: 50 },
        { source: "quiz_completed", xp: 0 },
        { source: "flashcard_reviewed", xp: 10 },
        { source: "study_session_completed", xp: 0 },
      ],
    },
    calendar: [{ day: "2026-08-08", xp: 20 }],
    calendarStart: "2026-08-06",
    calendarEnd: "2026-08-10",
    ...overrides,
  }
}

describe("calendarDays", () => {
  it("enumerates the window inclusively", () => {
    expect(calendarDays("2026-08-06", "2026-08-10")).toEqual([
      "2026-08-06",
      "2026-08-07",
      "2026-08-08",
      "2026-08-09",
      "2026-08-10",
    ])
  })

  it("returns a single day for a one-day window", () => {
    expect(calendarDays("2026-08-06", "2026-08-06")).toEqual(["2026-08-06"])
  })

  it("crosses a month boundary", () => {
    expect(calendarDays("2026-07-30", "2026-08-02")).toEqual([
      "2026-07-30",
      "2026-07-31",
      "2026-08-01",
      "2026-08-02",
    ])
  })

  it("crosses a leap day", () => {
    // Built by incrementing a real Date rather than by string arithmetic, so
    // this is the case that would catch a naive implementation.
    expect(calendarDays("2028-02-28", "2028-03-01")).toEqual([
      "2028-02-28",
      "2028-02-29",
      "2028-03-01",
    ])
  })

  it("returns nothing when the window is inverted", () => {
    expect(calendarDays("2026-08-10", "2026-08-06")).toEqual([])
  })
})

describe("fillCalendar", () => {
  it("renders every day of the window, not just the earning ones", () => {
    // The backend sends one entry; the grid must still be five cells wide, or
    // the window the caption states and the grid the student sees disagree.
    const filled = fillCalendar(profile())
    expect(filled).toHaveLength(5)
    expect(filled.map((d) => d.day)).toEqual(calendarDays("2026-08-06", "2026-08-10"))
  })

  it("gives an absent day exactly zero, the same as a zero day", () => {
    // D5.13 §4: the backend omits days that earned nothing precisely so "no
    // XP" and "outside the window" cannot be confused. Inside a known window,
    // an omitted day means zero and nothing else — there is no third state to
    // render.
    const filled = fillCalendar(profile())
    const absent = filled.find((d) => d.day === "2026-08-07")
    const explicitZero = fillCalendar(
      profile({ calendar: [{ day: "2026-08-07", xp: 0 }, { day: "2026-08-08", xp: 20 }] }),
    ).find((d) => d.day === "2026-08-07")
    expect(absent).toEqual(explicitZero)
    expect(absent?.xp).toBe(0)
  })

  it("keeps the XP of a day that earned some", () => {
    const filled = fillCalendar(profile())
    expect(filled.find((d) => d.day === "2026-08-08")?.xp).toBe(20)
  })

  it("handles a student who has earned nothing at all", () => {
    // A brand-new account: every cell is a real zero, and the grid still
    // renders rather than collapsing to an empty state.
    const filled = fillCalendar(profile({ calendar: [] }))
    expect(filled).toHaveLength(5)
    expect(filled.every((d) => d.xp === 0)).toBe(true)
  })
})

describe("levelProgress", () => {
  it("reads the band off the wire rather than re-deriving the curve", () => {
    // 250 total, band 100..400 → 150/300 → 50%. If this ever needs a
    // `Math.sqrt`, the curve has leaked into the client (D5.13 §1).
    expect(levelProgress(profile())).toBe(50)
  })

  it("is 0 at the start of a level and 100 at its end", () => {
    expect(levelProgress(profile({ totalXp: 100 }))).toBe(0)
    expect(levelProgress(profile({ totalXp: 400 }))).toBe(100)
  })

  it("clamps rather than overflowing the bar", () => {
    expect(levelProgress(profile({ totalXp: 900 }))).toBe(100)
    expect(levelProgress(profile({ totalXp: 10 }))).toBe(0)
  })

  it("returns 0 for a degenerate band instead of NaN", () => {
    // Guaranteed not to happen on the wire, but a NaN width renders as an
    // empty bar, which reads as "no progress" rather than as the bug it is.
    const degenerate = levelProgress(
      profile({ levelStartXp: 400, nextLevelXp: 400 }),
    )
    expect(degenerate).toBe(0)
    expect(Number.isNaN(degenerate)).toBe(false)
  })
})

describe("sourceLabel", () => {
  it("names the four known sources", () => {
    expect(sourceLabel("paper_corrected")).toBe("Papers corrected")
    expect(sourceLabel("quiz_completed")).toBe("Quizzes")
    expect(sourceLabel("flashcard_reviewed")).toBe("Flashcards")
    expect(sourceLabel("study_session_completed")).toBe("Study sessions")
  })

  it("falls back readably rather than dropping an unknown source", () => {
    // Dropping the row would understate the week against the `total` printed
    // beside it — a visible inconsistency, and the wrong failure mode.
    expect(sourceLabel("something_new")).toBe("something new")
  })
})
