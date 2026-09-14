import { describe, expect, it } from "vitest"
import { GESTURE_INTERACTIVE_SELECTOR, isInteractiveTagOrRole } from "@/lib/gestures/interactiveSelector"

/*
 * Consolidation pass · the single source of truth for "is this element one
 * that already owns its own click/tap" — union of what four separate gesture
 * call sites (useLongPress, QuizTaker's page-turn swipe, FlashcardReview's
 * card swipe, quizSwipe's pure decision) used to each list ad hoc. Two forms
 * are exported because two different call shapes need it: a live DOM node
 * (`.closest(GESTURE_INTERACTIVE_SELECTOR)`) and an already-extracted
 * tag/role pair with no DOM available (`quizSwipe.ts`'s pure, Node-testable
 * decision function).
 */

describe("GESTURE_INTERACTIVE_SELECTOR", () => {
  it("matches every element kind the four call sites used to list separately", () => {
    for (const tag of ["button", "a", "input", "textarea", "select", "label"]) {
      expect(GESTURE_INTERACTIVE_SELECTOR).toContain(tag)
    }
    expect(GESTURE_INTERACTIVE_SELECTOR).toContain('[role="radio"]')
    expect(GESTURE_INTERACTIVE_SELECTOR).toContain('[role="checkbox"]')
    expect(GESTURE_INTERACTIVE_SELECTOR).toContain('[role="button"]')
  })
})

describe("isInteractiveTagOrRole", () => {
  it.each(["BUTTON", "A", "INPUT", "TEXTAREA", "SELECT", "LABEL"])(
    "treats a %s tag as interactive",
    (tag) => {
      expect(isInteractiveTagOrRole(tag, null)).toBe(true)
    },
  )

  it("is case-insensitive on the tag name", () => {
    expect(isInteractiveTagOrRole("button", null)).toBe(true)
  })

  it.each(["radio", "checkbox", "button"])("treats role=%s as interactive regardless of tag", (role) => {
    expect(isInteractiveTagOrRole("DIV", role)).toBe(true)
  })

  it("is false for a plain non-interactive tag with no role", () => {
    expect(isInteractiveTagOrRole("DIV", null)).toBe(false)
  })
})
