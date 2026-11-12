import { describe, expect, it } from "vitest"
import { daysUntil, formatCountdown } from "@/lib/countdown"

/*
 * C3b · Moved out of `announcements.test.ts` when `daysUntil`/`formatCountdown`
 * moved to `lib/countdown.ts` so `StudyPlanWeek.tsx` could share them without
 * importing across screens. Every assertion here is unchanged from where it
 * used to live; this is the whole reason the move is safe — the countdown is
 * the most prominent number on both screens, and if it is off by a day the
 * failure is silent everywhere it appears.
 */

describe("daysUntil", () => {
  it("counts whole calendar days, not elapsed hours", () => {
    // The defect this prevents: a student checking at 23:00 and again at
    // 01:00 watching "3 days" become "2 days" overnight when the exam is the
    // same calendar distance away.
    const lateEvening = new Date(2026, 4, 9, 23, 30)
    const smallHours = new Date(2026, 4, 10, 1, 15)
    expect(daysUntil("2026-05-12", lateEvening)).toBe(3)
    expect(daysUntil("2026-05-12", smallHours)).toBe(2)
  })

  it("is 0 on the day of the exam", () => {
    expect(daysUntil("2026-05-12", new Date(2026, 4, 12, 6, 0))).toBe(0)
  })

  it("is 1 the day before the exam", () => {
    expect(daysUntil("2026-05-12", new Date(2026, 4, 11, 6, 0))).toBe(1)
  })

  it("goes negative once the exam has passed", () => {
    expect(daysUntil("2026-05-12", new Date(2026, 4, 13, 6, 0))).toBe(-1)
  })

  it("counts across a month boundary", () => {
    expect(daysUntil("2026-06-02", new Date(2026, 4, 31, 12, 0))).toBe(2)
  })

  it("counts an arbitrary n-day distance", () => {
    expect(daysUntil("2026-06-22", new Date(2026, 4, 12, 9, 0))).toBe(41)
  })
})

describe("formatCountdown", () => {
  it("says Today and Tomorrow rather than a bare number", () => {
    expect(formatCountdown(0)).toBe("Today")
    expect(formatCountdown(1)).toBe("Tomorrow")
  })

  it("pluralises everything else", () => {
    expect(formatCountdown(2)).toBe("2 days")
    expect(formatCountdown(41)).toBe("41 days")
  })
})
