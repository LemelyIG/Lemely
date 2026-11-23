import { describe, expect, it } from "vitest"
import { canGradeCard, isEditableTarget, isForeignControl } from "@/portals/student/screens/flashcards/reviewProgression"

describe("review progression", () => {
  it("allows a revealed card to be graded only once", () => {
    expect(canGradeCard("card-1", true, new Set())).toBe(true)
    expect(canGradeCard("card-1", false, new Set())).toBe(false)
    expect(canGradeCard("card-1", true, new Set(["card-1"]))).toBe(false)
    expect(canGradeCard(null, true, new Set())).toBe(false)
  })

  it("recognizes editable targets, including contenteditable descendants", () => {
    expect(isEditableTarget({ closest: () => ({}) })).toBe(true)
    expect(isEditableTarget({ closest: () => null })).toBe(false)
    expect(isEditableTarget(null)).toBe(false)
  })

  it("treats another button or link as owning Space and Enter, but not the review's own controls", () => {
    const control = (own: boolean) => ({ closest: () => ({ hasAttribute: (n: string) => own && n === "data-review-primary" }) })
    expect(isForeignControl(control(false))).toBe(true)
    expect(isForeignControl(control(true))).toBe(false)
    expect(isForeignControl({ closest: () => null })).toBe(false)
    expect(isForeignControl(null)).toBe(false)
  })
})
