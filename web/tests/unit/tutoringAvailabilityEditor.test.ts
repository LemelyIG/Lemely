import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"
import {
  DST_NOTE_FOR,
  MAX_RULES,
  MINUTES_PER_DAY,
  NO_RULES_LINE,
  SPLIT_NOTE_LINE,
  STEP_MINUTES,
  WEEKDAYS,
  addRange,
  crossesMidnight,
  emptyWeek,
  endOptions,
  formatMinute,
  removeRange,
  rulesFromWeek,
  splitNotice,
  startOptions,
  updateRange,
  validateWeek,
  weekFromRules,
  weekIsDirty,
  type WeekDraft,
} from "@/lib/tutoring/availabilityEditor"
import type { AvailabilityRule } from "@/lib/tutoringTypes"

/*
 * T-17 (SPEC §d, §a.2, §a.4): the weekly availability editor.
 *
 * Every expected side is read out of the SPEC text: the step size and the two
 * fixed lines from the T-17 block, the rule cap from the T5 route row, and the
 * "crossing midnight is two rules" rule from the table notes. Nothing is
 * compared with a literal written from the same source as the code.
 */

const SPEC = readFileSync(
  join(import.meta.dirname, "..", "..", "..", "docs", "tutoring", "SPEC.md"),
  "utf8",
)

function t17Block(): string {
  const start = SPEC.indexOf("**T-17 ·")
  const end = SPEC.indexOf("**T-18 ·", start)
  expect(start).toBeGreaterThan(-1)
  expect(end).toBeGreaterThan(start)
  return SPEC.slice(start, end)
}

const BLOCK = t17Block()
const SPEC_DST = /"(Cairo time; daylight saving[^"]+)"/.exec(BLOCK)?.[1] ?? ""
const SPEC_EMPTY = /No rules: "([^"]+)"/.exec(BLOCK)?.[1] ?? ""
const SPEC_STEP = Number(/\((\d+)-minute steps/.exec(BLOCK)?.[1] ?? "0")
const SPEC_MAX = Number(/`AvailabilityReplaceDTO` \((\d+)–(\d+) rules\)/.exec(SPEC)?.[2] ?? "0")

const rule = (isoWeekday: number, startMinute: number, endMinute: number): AvailabilityRule => ({
  isoWeekday,
  startMinute,
  endMinute,
})

function weekWith(entries: [number, number, number][]): WeekDraft {
  let week = emptyWeek()
  entries.forEach(([weekday, start, end], i) => {
    week = {
      ...week,
      [weekday]: [...week[weekday as 1], { id: `r${i}`, startMinute: start, endMinute: end }],
    }
  })
  return week
}

describe("what the SPEC says (parsed, so the checks below cannot agree with a stale copy)", () => {
  it("parses a step, a cap and the two fixed lines out of the SPEC", () => {
    expect(SPEC_STEP).toBe(15)
    expect(SPEC_MAX).toBe(42)
    expect(SPEC_DST.length).toBeGreaterThan(40)
    expect(SPEC_EMPTY.length).toBeGreaterThan(10)
  })

  it("uses the SPEC step and cap", () => {
    expect(STEP_MINUTES).toBe(SPEC_STEP)
    expect(MAX_RULES).toBe(SPEC_MAX)
    expect(MINUTES_PER_DAY).toBe(24 * 60)
  })

  it("words the daylight saving note as the SPEC does, with the tutor's zone label", () => {
    expect(DST_NOTE_FOR("Cairo time")).toBe(SPEC_DST)
  })

  it("words the empty line as the SPEC does", () => {
    expect(NO_RULES_LINE).toBe(SPEC_EMPTY)
  })

  it("lists seven weekdays, Monday first, with ISO numbers 1 to 7", () => {
    expect(WEEKDAYS.map((d) => d.iso)).toEqual([1, 2, 3, 4, 5, 6, 7])
    expect(WEEKDAYS[0].label).toBe("Monday")
    expect(WEEKDAYS[6].label).toBe("Sunday")
  })

  it("says that a window across midnight is saved as two", () => {
    expect(SPLIT_NOTE_LINE.toLowerCase()).toContain("two")
    expect(BLOCK + SPEC).toContain("A window crossing midnight is two rules")
  })
})

describe("15-minute steps", () => {
  it("offers 96 start times, every one on a quarter hour, none at or after midnight", () => {
    const starts = startOptions()
    expect(starts).toHaveLength(96)
    expect(starts[0]).toBe(0)
    expect(starts.at(-1)).toBe(MINUTES_PER_DAY - STEP_MINUTES)
    expect(starts.every((m) => m % STEP_MINUTES === 0)).toBe(true)
  })

  it("offers 96 end times from 00:15 to 24:00, every one on a quarter hour", () => {
    const ends = endOptions()
    expect(ends).toHaveLength(96)
    expect(ends[0]).toBe(STEP_MINUTES)
    expect(ends.at(-1)).toBe(MINUTES_PER_DAY)
    expect(ends.every((m) => m % STEP_MINUTES === 0)).toBe(true)
  })

  it("writes minutes as clock times, midnight at the end of the day as 24:00", () => {
    expect(formatMinute(0)).toBe("00:00")
    expect(formatMinute(9 * 60 + 15)).toBe("09:15")
    expect(formatMinute(23 * 60 + 45)).toBe("23:45")
    expect(formatMinute(MINUTES_PER_DAY)).toBe("24:00")
  })

  it("refuses a time that is not on a quarter hour", () => {
    const { problems } = validateWeek(weekWith([[1, 9 * 60 + 5, 10 * 60]]))
    expect(problems.map((p) => p.kind)).toContain("step")
    const second = validateWeek(weekWith([[1, 9 * 60, 10 * 60 + 7]]))
    expect(second.problems.map((p) => p.kind)).toContain("step")
  })

  it("accepts every quarter-hour start with the next quarter hour as its end", () => {
    for (const start of startOptions()) {
      const { problems } = validateWeek(weekWith([[3, start, start + STEP_MINUTES]]))
      expect(problems, `start ${start}`).toEqual([])
    }
  })
})

describe("a rule crossing midnight is two rules", () => {
  it("knows which windows cross midnight", () => {
    expect(crossesMidnight({ id: "a", startMinute: 22 * 60, endMinute: 2 * 60 })).toBe(true)
    expect(crossesMidnight({ id: "a", startMinute: 9 * 60, endMinute: 10 * 60 })).toBe(false)
    expect(crossesMidnight({ id: "a", startMinute: 20 * 60, endMinute: MINUTES_PER_DAY })).toBe(false)
  })

  it("splits Monday 22:00 to 02:00 into Monday 22:00-24:00 and Tuesday 00:00-02:00", () => {
    const rules = rulesFromWeek(weekWith([[1, 22 * 60, 2 * 60]]))
    expect(rules).toEqual([rule(1, 22 * 60, MINUTES_PER_DAY), rule(2, 0, 2 * 60)])
  })

  it("wraps Sunday into Monday", () => {
    const rules = rulesFromWeek(weekWith([[7, 23 * 60, 60]]))
    expect(rules).toEqual([rule(1, 0, 60), rule(7, 23 * 60, MINUTES_PER_DAY)])
  })

  it("does not split a window that ends exactly at midnight", () => {
    const rules = rulesFromWeek(weekWith([[5, 20 * 60, MINUTES_PER_DAY]]))
    expect(rules).toEqual([rule(5, 20 * 60, MINUTES_PER_DAY)])
  })

  it("does not split a window inside one day", () => {
    expect(rulesFromWeek(weekWith([[2, 9 * 60, 11 * 60]]))).toEqual([rule(2, 9 * 60, 11 * 60)])
  })

  it("never produces a rule that spans midnight, whatever the input", () => {
    for (const start of startOptions().filter((m) => m % 60 === 0)) {
      for (const end of endOptions().filter((m) => m % 60 === 0)) {
        if (end === start) continue
        for (const rule of rulesFromWeek(weekWith([[4, start, end]]))) {
          expect(rule.startMinute).toBeGreaterThanOrEqual(0)
          expect(rule.endMinute).toBeLessThanOrEqual(MINUTES_PER_DAY)
          expect(rule.endMinute).toBeGreaterThan(rule.startMinute)
        }
      }
    }
  })

  it("explains the split in words before it is saved", () => {
    expect(splitNotice(1, { id: "a", startMinute: 22 * 60, endMinute: 2 * 60 })).toBe(
      "Saved as two windows: Monday 22:00 to 24:00 and Tuesday 00:00 to 02:00.",
    )
    expect(splitNotice(7, { id: "a", startMinute: 23 * 60, endMinute: 60 })).toBe(
      "Saved as two windows: Sunday 23:00 to 24:00 and Monday 00:00 to 01:00.",
    )
    expect(splitNotice(1, { id: "a", startMinute: 9 * 60, endMinute: 10 * 60 })).toBeNull()
  })

  it("counts the two halves against the cap of 42", () => {
    const entries: [number, number, number][] = []
    for (let i = 0; i < 22; i++) entries.push([(i % 6) + 1, i * 15, i * 15 + 15])
    const ok = validateWeek(weekWith(entries))
    expect(ok.ruleCount).toBe(22)
    expect(ok.tooMany).toBe(false)

    // 22 windows that each cross midnight is 44 rules.
    const crossing: [number, number, number][] = []
    for (let i = 0; i < 22; i++) crossing.push([(i % 7) + 1, 1320 + (i % 7) * 15, 15 + i * 15])
    const over = validateWeek(weekWith(crossing))
    expect(over.ruleCount).toBe(44)
    expect(over.tooMany).toBe(true)
  })
})

describe("overlap and bounds", () => {
  it("lets windows touch but not overlap", () => {
    expect(validateWeek(weekWith([[1, 9 * 60, 10 * 60], [1, 10 * 60, 11 * 60]])).problems).toEqual([])
    const bad = validateWeek(weekWith([[1, 9 * 60, 11 * 60], [1, 10 * 60, 12 * 60]]))
    expect(bad.problems.map((p) => p.kind)).toEqual(["overlap", "overlap"])
    expect(bad.problems.map((p) => p.rangeId).sort()).toEqual(["r0", "r1"])
  })

  it("finds an overlap with a window that is not the next one in order", () => {
    const bad = validateWeek(
      weekWith([[2, 8 * 60, 18 * 60], [2, 9 * 60, 10 * 60], [2, 12 * 60, 13 * 60]]),
    )
    expect(bad.problems.filter((p) => p.kind === "overlap").map((p) => p.rangeId).sort()).toEqual([
      "r0",
      "r1",
      "r2",
    ])
  })

  it("sees the spill of a late window overlapping an early one the next day", () => {
    const bad = validateWeek(weekWith([[1, 22 * 60, 2 * 60], [2, 60, 3 * 60]]))
    expect(bad.problems.map((p) => p.kind)).toContain("overlap")
  })

  it("refuses a window that starts and ends at the same time", () => {
    const { problems } = validateWeek(weekWith([[1, 9 * 60, 9 * 60]]))
    expect(problems.map((p) => p.kind)).toEqual(["empty"])
  })

  it("refuses times outside the day", () => {
    expect(validateWeek(weekWith([[1, -15, 60]])).problems.map((p) => p.kind)).toContain("bounds")
    expect(validateWeek(weekWith([[1, 60, MINUTES_PER_DAY + 15]])).problems.map((p) => p.kind)).toContain(
      "bounds",
    )
    expect(validateWeek(weekWith([[1, MINUTES_PER_DAY, 15]])).problems.map((p) => p.kind)).toContain("bounds")
  })

  it("gives each problem a sentence that says what to change", () => {
    const { problems } = validateWeek(weekWith([[1, 9 * 60, 11 * 60], [1, 10 * 60, 12 * 60]]))
    for (const problem of problems) expect(problem.message.length).toBeGreaterThan(15)
  })

  it("accepts an empty week", () => {
    const { problems, ruleCount } = validateWeek(emptyWeek())
    expect(problems).toEqual([])
    expect(ruleCount).toBe(0)
  })
})

describe("reading rules back and editing", () => {
  const saved = [rule(1, 9 * 60, 12 * 60), rule(1, 14 * 60, 17 * 60), rule(3, 18 * 60, MINUTES_PER_DAY), rule(4, 0, 60)]

  it("shows stored rules per day in time order and returns the same rules on save", () => {
    const week = weekFromRules([saved[3], saved[1], saved[0], saved[2]])
    expect(week[1].map((r) => r.startMinute)).toEqual([9 * 60, 14 * 60])
    expect(week[2]).toEqual([])
    expect(rulesFromWeek(week)).toEqual(saved)
  })

  it("keeps the two stored halves of a midnight window as two rows", () => {
    const week = weekFromRules([rule(1, 22 * 60, MINUTES_PER_DAY), rule(2, 0, 2 * 60)])
    expect(week[1]).toHaveLength(1)
    expect(week[2]).toHaveLength(1)
    expect(rulesFromWeek(week)).toHaveLength(2)
  })

  it("is dirty only when the rules differ from what is saved", () => {
    const week = weekFromRules(saved)
    expect(weekIsDirty(week, saved)).toBe(false)
    expect(weekIsDirty(updateRange(week, 1, week[1][0].id, { endMinute: 13 * 60 }), saved)).toBe(true)
    expect(weekIsDirty(removeRange(week, 4, week[4][0].id), saved)).toBe(true)
  })

  it("adds a window on a day after the last one, valid, and removes by id", () => {
    let week = weekFromRules(saved)
    week = addRange(week, 1)
    expect(week[1]).toHaveLength(3)
    expect(validateWeek(week).problems).toEqual([])
    const added = week[1].find((r) => r.startMinute >= 17 * 60)
    expect(added).toBeDefined()
    expect(week[1].every((r) => r.id.length > 0)).toBe(true)
    expect(new Set(week[1].map((r) => r.id)).size).toBe(3)
    week = removeRange(week, 1, added!.id)
    expect(week[1]).toHaveLength(2)
  })

  it("adds a window on a day that is already full to the end of the day without breaking validation", () => {
    let week = weekFromRules([rule(6, 0, MINUTES_PER_DAY)])
    week = addRange(week, 6)
    // No free quarter hour is left: the new row exists but the editor reports the overlap.
    expect(week[6]).toHaveLength(2)
    expect(validateWeek(week).problems.map((p) => p.kind)).toContain("overlap")
  })
})
