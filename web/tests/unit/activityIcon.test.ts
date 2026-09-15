import { describe, expect, it } from "vitest"
import { PencilSimple, Cards, FileText, BookOpen, Circle } from "@phosphor-icons/react"
import { activityIcon } from "@/portals/student/screens/studyplan/studyPlanData"

/*
 * C3b · `SessionRow`'s leading activity glyph. Pinned as an exact icon
 * identity per activity type, plus the `Circle` fallback for a value this
 * build does not recognise — the same "render verbatim rather than guess"
 * posture `activityLabel` already takes for an unmapped `activityType`.
 */

describe("activityIcon", () => {
  it("maps practice to PencilSimple", () => {
    expect(activityIcon("practice")).toBe(PencilSimple)
  })

  it("maps flashcards to Cards", () => {
    expect(activityIcon("flashcards")).toBe(Cards)
  })

  it("maps past_paper to FileText", () => {
    expect(activityIcon("past_paper")).toBe(FileText)
  })

  it("maps review to BookOpen", () => {
    expect(activityIcon("review")).toBe(BookOpen)
  })

  it("falls back to Circle for an unrecognised activity type", () => {
    expect(activityIcon("something_new")).toBe(Circle)
  })
})
