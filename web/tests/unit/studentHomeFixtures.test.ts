import { describe, expect, it } from "vitest"
import { binnyMood, deriveNextAction } from "@/portals/student/home/model"
import { FIXTURES, STATES } from "../../dev-previews/student-home/fixtures"

describe("student home preview fixtures", () => {
  it("covers every spec state", () => {
    expect([...STATES].sort()).toEqual(
      ["error", "loading", "marking", "new", "no-exams", "no-plan", "one-paper", "populated", "streak-zero"],
    )
  })

  for (const id of STATES) {
    it(`${id} drives the action and mood it claims`, () => {
      const { facts, expected } = FIXTURES[id]
      expect(deriveNextAction(facts).kind).toBe(expected.action)
      expect(binnyMood(facts)).toBe(expected.mood)
    })
  }

  it("no-exams has no exam dates and populated has all of them", () => {
    expect(FIXTURES["no-exams"].facts.subjects.every((s) => s.nextExamOn === null)).toBe(true)
    expect(FIXTURES.populated.facts.subjects.every((s) => s.nextExamOn !== null)).toBe(true)
  })

  it("streak-zero has no XP today or yesterday", () => {
    const cal = FIXTURES["streak-zero"].facts.calendar
    expect(cal.some((d) => (d.day === "2026-11-05" || d.day === "2026-11-04") && d.xp > 0)).toBe(false)
  })
})
