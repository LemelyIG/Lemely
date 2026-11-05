import { describe, expect, it } from "vitest"
import { gradeChipClass, gradeTone } from "@/lib/grade"

describe("gradeTone", () => {
  it.each([
    ["A*", "a-star"], ["A", "a"], ["B", "b"], ["C", "c"], ["D", "d"], ["E", "e"], ["F", "f"], ["G", "g"], ["U", "u"],
    ["a*", "a-star"], [" b ", "b"],
  ])("%s maps to %s", (grade, tone) => expect(gradeTone(grade)).toBe(tone))

  it.each(["", "H", "9", "A**"])("%s has no tone", (grade) => expect(gradeTone(grade)).toBeNull())
})

/*
 * White letters clear only large-text AA (3:1) on the Jewel fills
 * (tests/test_design_tokens.py), so the filled chip is opt-in for a large
 * letter and the default is the outlined chip with an on-surface letter.
 */
describe("gradeChipClass", () => {
  it("defaults to the outlined small chip, never a white letter", () => {
    expect(gradeChipClass("B")).toBe("border-2 border-grade-b bg-surface-container-lowest text-on-surface")
    expect(gradeChipClass("A*", { size: "small" })).not.toMatch(/text-white|bg-grade/)
  })

  it("fills with a white letter only when the letter is large text", () => {
    expect(gradeChipClass("A*", { size: "large" })).toBe("bg-grade-a-star text-white")
  })

  it.each([["F", "f"], ["G", "g"]])("gives Core-tier %s its own Jewel chip", (grade, tone) => {
    expect(gradeChipClass(grade)).toBe(`border-2 border-grade-${tone} bg-surface-container-lowest text-on-surface`)
    expect(gradeChipClass(grade, { size: "large" })).toBe(`bg-grade-${tone} text-white`)
  })

  it.each(["small", "large"] as const)("gives an unknown grade a neutral %s chip", (size) => {
    expect(gradeChipClass("H", { size })).not.toMatch(/grade-|text-white/)
  })
})
