import { describe, expect, it } from "vitest"
import { gradeTone } from "@/lib/grade"

describe("gradeTone", () => {
  it.each([
    ["A*", "a-star"], ["A", "a"], ["B", "b"], ["C", "c"], ["D", "d"], ["E", "e"], ["U", "u"],
    ["a*", "a-star"], [" b ", "b"],
  ])("%s maps to %s", (grade, tone) => expect(gradeTone(grade)).toBe(tone))

  it.each(["", "F", "9", "A**"])("%s has no tone", (grade) => expect(gradeTone(grade)).toBeNull())
})
