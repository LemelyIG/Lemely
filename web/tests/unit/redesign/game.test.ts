import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { afterEach, describe, expect, it } from "vitest"
import { ComboChip, CountdownPill, LevelBar, countdownTone } from "@/components/redesign"
import { countdownLabel, daysUntil } from "@/components/redesign/countdown"
import { comboRose, comboVisible, levelFraction } from "@/components/redesign/game"

const NOW = new Date(2026, 10, 15, 21, 30) // 15 Nov 2026, late evening local time

describe("combo", () => {
  it("is hidden below 2 and bumps only on a rise", () => {
    expect([comboVisible(1), comboVisible(2)]).toEqual([false, true])
    expect([comboRose(2, 3), comboRose(3, 3), comboRose(4, 2)]).toEqual([true, false, false])
  })
  it("renders nothing below 2", () => {
    expect(renderToStaticMarkup(createElement(ComboChip, { count: 1 }))).toBe("")
  })
  it("shows ×N with a spoken name", () => {
    const out = renderToStaticMarkup(createElement(ComboChip, { count: 3 }))
    expect(out).toMatch(/^<span class="rd-combo">/)
    expect(out).toContain('<span aria-hidden="true">×3</span>')
    expect(out).toContain('<span class="sr-only">Combo of 3</span>')
  })
  it("never shows on junk counts and floors a fractional one", () => {
    for (const bad of [Number.NaN, -4, Number.POSITIVE_INFINITY, 0, 1.9]) {
      expect(comboVisible(bad), String(bad)).toBe(false)
      expect(renderToStaticMarkup(createElement(ComboChip, { count: bad })), String(bad)).toBe("")
    }
    expect(renderToStaticMarkup(createElement(ComboChip, { count: 2.7 }))).toContain("×2<")
  })
  it("keeps a four digit combo on one line", () => {
    expect(renderToStaticMarkup(createElement(ComboChip, { count: 1234 }))).toContain("×1234")
  })
})

describe("LevelBar", () => {
  it("fills gold by xp over nextXp and reads as a progressbar", () => {
    expect([levelFraction(240, 500), levelFraction(10, 0), levelFraction(900, 500)]).toEqual([0.48, 0, 1])
    const out = renderToStaticMarkup(createElement(LevelBar, { level: 7, xp: 240, nextXp: 500 }))
    expect(out).toContain("<b>Level 7</b>")
    expect(out).toMatch(/role="progressbar"[^>]*aria-valuenow="240"[^>]*aria-valuetext="240 of 500 XP"/)
    expect(out).toContain('style="width:48%"')
    expect(out).toContain("<small>240 / 500 XP</small>")
  })
  it("survives overflow, negatives, NaN and a missing next level", () => {
    expect([levelFraction(-5, 500), levelFraction(Number.NaN, 500), levelFraction(5, Number.NaN)]).toEqual([0, 0, 0])
    const over = renderToStaticMarkup(createElement(LevelBar, { level: 2, xp: 900, nextXp: 500 }))
    expect(over).toContain('style="width:100%"')
    expect(over).toContain('aria-valuenow="500"')
    const top = renderToStaticMarkup(createElement(LevelBar, { level: 30, xp: 12000, nextXp: 0 }))
    expect(top).toContain('style="width:0%"')
    expect(top).toContain("<small>12000 XP</small>")
    expect(top).not.toContain("aria-valuemax=\"0\"")
    expect(renderToStaticMarkup(createElement(LevelBar, { level: 1, xp: -20, nextXp: 100 }))).toContain('aria-valuenow="0"')
  })
})

describe("countdown", () => {
  it("counts whole local days, ignoring the time of day", () => {
    expect(daysUntil("2026-11-16", NOW)).toBe(1)
    expect(daysUntil("2026-11-15", NOW)).toBe(0)
    expect(daysUntil("2027-05-14T09:00:00Z", NOW)).toBe(180)
  })
  it("turns near inside 30 days, neutral otherwise and after the exam", () => {
    expect([countdownTone("2026-12-15", NOW), countdownTone("2026-12-16", NOW), countdownTone("2026-11-14", NOW)]).toEqual(["near", "neutral", "neutral"])
  })
  it("labels", () => {
    expect(countdownLabel(180)).toBe("180 days to exams")
    expect(countdownLabel(1, "Physics")).toBe("1 day to Physics")
    expect(countdownLabel(0)).toBe("Exams today")
    expect(countdownLabel(188, null)).toBe("188 days")
    expect(countdownLabel(-1)).toBeNull()
  })
  it("renders a neutral pill, a near pill, and nothing after the exam", () => {
    expect(renderToStaticMarkup(createElement(CountdownPill, { examDate: "2027-05-14", now: NOW }))).toMatch(/data-tone="neutral".*180 days to exams/)
    expect(renderToStaticMarkup(createElement(CountdownPill, { examDate: "2026-12-01", now: NOW }))).toMatch(/data-tone="near"/)
    expect(renderToStaticMarkup(createElement(CountdownPill, { examDate: "2026-11-01", now: NOW }))).toBe("")
  })
})

describe("countdown boundaries", () => {
  it("is the same all day: 00:00:00.000 and 23:59:59.999 agree", () => {
    const start = new Date(2026, 10, 15, 0, 0, 0, 0)
    const end = new Date(2026, 10, 15, 23, 59, 59, 999)
    expect([daysUntil("2026-11-16", start), daysUntil("2026-11-16", end)]).toEqual([1, 1])
    expect([daysUntil("2026-11-15", start), daysUntil("2026-11-15", end)]).toEqual([0, 0])
    expect(daysUntil("2026-11-14", end)).toBe(-1)
  })
  it("flips on the stroke of local midnight", () => {
    expect(daysUntil("2026-11-16", new Date(2026, 10, 15, 23, 59, 59, 999))).toBe(1)
    expect(daysUntil("2026-11-16", new Date(2026, 10, 16, 0, 0, 0, 0))).toBe(0)
  })
  it("pins the 30 day edge exactly", () => {
    expect([countdownTone("2026-12-15", NOW), countdownTone("2026-12-16", NOW)]).toEqual(["near", "neutral"])
    expect([daysUntil("2026-12-15", NOW), daysUntil("2026-12-16", NOW)]).toEqual([30, 31])
    expect(countdownTone("2026-11-15", NOW)).toBe("near")
  })
  it("treats today as 'Exams today' and the day after as gone", () => {
    expect(renderToStaticMarkup(createElement(CountdownPill, { examDate: "2026-11-15", now: NOW }))).toContain("Exams today")
    expect(renderToStaticMarkup(createElement(CountdownPill, { examDate: "2026-11-14", now: NOW }))).toBe("")
    expect(renderToStaticMarkup(createElement(CountdownPill, { examDate: "2026-11-15", now: NOW, subject: "Physics" }))).toContain("Physics today")
  })
  it("rejects junk dates instead of printing NaN", () => {
    for (const bad of ["", "soon", "2026-13-40", "2026-02-30", "15/11/2026"]) {
      expect(Number.isNaN(daysUntil(bad, NOW)), bad).toBe(true)
      expect(countdownLabel(daysUntil(bad, NOW)), bad).toBeNull()
      expect(countdownTone(bad, NOW), bad).toBe("neutral")
      expect(renderToStaticMarkup(createElement(CountdownPill, { examDate: bad, now: NOW })), bad).toBe("")
    }
    expect(renderToStaticMarkup(createElement(CountdownPill, { examDate: "2027-05-14", now: new Date("nope") }))).toBe("")
  })
  it("accepts a date-time stamp and uses its calendar date", () => {
    expect(daysUntil("2026-11-16T23:30:00", NOW)).toBe(1)
  })
})

describe("countdown across DST and zones", () => {
  const original = process.env.TZ
  afterEach(() => {
    if (original === undefined) delete process.env.TZ
    else process.env.TZ = original
  })
  // Each row: zone, a local "now", an exam date, the expected whole-day gap.
  const zones: [string, () => Date, string, number][] = [
    ["America/New_York", () => new Date(2026, 2, 7, 22, 0), "2026-03-09", 2], // spring forward 8 Mar, 23h day
    ["America/New_York", () => new Date(2026, 2, 8, 1, 59), "2026-03-09", 1],
    ["America/New_York", () => new Date(2026, 10, 1, 0, 30), "2026-11-02", 1], // fall back 1 Nov, 25h day
    ["America/New_York", () => new Date(2026, 9, 31, 23, 59), "2026-11-02", 2],
    ["Europe/London", () => new Date(2026, 2, 28, 23, 59), "2026-03-30", 2], // spring forward 29 Mar
    ["Europe/London", () => new Date(2026, 9, 24, 23, 59), "2026-10-26", 2], // fall back 25 Oct
    ["Africa/Cairo", () => new Date(2026, 3, 23, 23, 59), "2026-04-25", 2], // Egypt DST returns late April
    ["Pacific/Kiritimati", () => new Date(2026, 10, 15, 23, 59), "2026-11-16", 1], // UTC+14
    ["Pacific/Pago_Pago", () => new Date(2026, 10, 15, 0, 1), "2026-11-16", 1], // UTC-11
    ["UTC", () => new Date(2026, 10, 15, 12, 0), "2026-11-15", 0],
  ]
  for (const [zone, make, exam, want] of zones) {
    it(`${zone}: ${exam} is ${want} away`, () => {
      process.env.TZ = zone
      expect(daysUntil(exam, make())).toBe(want)
    })
  }
})
