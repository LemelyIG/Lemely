import { describe, expect, it } from "vitest"
import { plural, subjectDotColor, topicLabel, tryOthers } from "@/portals/student/screens/practice/practiceCopy"

describe("practiceCopy", () => {
  it("plural picks the singular only for exactly one", () => {
    expect(plural(1, "topic")).toBe("1 topic")
    expect(plural(0, "topic")).toBe("0 topics")
    expect(plural(3, "match", "matches")).toBe("3 matches")
  })

  it("topicLabel drops syllabus numbering but never empties a label", () => {
    expect(topicLabel("1.2 Motion")).toBe("Motion")
    expect(topicLabel("3 Waves and light")).toBe("Waves and light")
    expect(topicLabel("Vectors")).toBe("Vectors")
    expect(topicLabel("12")).toBe("12")
  })

  it("tryOthers names the other subjects, or says to check back", () => {
    expect(tryOthers([])).toBe("We're adding them. Check back soon.")
    expect(tryOthers(["Physics"])).toBe("We're adding them. Try Physics for now.")
    expect(tryOthers(["Maths", "Physics"])).toBe("We're adding them. Try Maths or Physics for now.")
    expect(tryOthers(["Maths", "Physics", "Chemistry"])).toBe(
      "We're adding them. Try Maths, Physics or Chemistry for now.",
    )
  })

  it("subjectDotColor is stable by subject order and only uses tokens", () => {
    const codes = ["0580", "0625", "0606"]
    expect(subjectDotColor("0580", codes)).toBe("var(--color-grade-a)")
    expect(subjectDotColor("0625", codes)).toBe("var(--color-primary)")
    expect(subjectDotColor("9999", codes)).toBe("var(--color-outline)")
  })
})
