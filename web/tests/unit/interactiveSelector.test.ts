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

  // Issue #246/#247, Minor-5: latent at the time it was found (no control on
  // any of the three pull-to-refresh screens used any of these), but the
  // same click-swallowing bug class reaches a custom tab strip, a menu, or
  // an editable region just as easily as a `<button>`.
  it("matches summary, and role=link/switch/tab/menuitem", () => {
    expect(GESTURE_INTERACTIVE_SELECTOR).toContain("summary")
    for (const role of ["link", "switch", "tab", "menuitem"]) {
      expect(GESTURE_INTERACTIVE_SELECTOR).toContain(`[role="${role}"]`)
    }
  })

  it("matches contenteditable regions and anything with a real tabindex", () => {
    expect(GESTURE_INTERACTIVE_SELECTOR).toContain("[contenteditable]")
    expect(GESTURE_INTERACTIVE_SELECTOR).toContain('[tabindex]:not([tabindex="-1"])')
  })
})

describe("isInteractiveTagOrRole", () => {
  it.each(["BUTTON", "A", "INPUT", "TEXTAREA", "SELECT", "LABEL", "SUMMARY"])(
    "treats a %s tag as interactive",
    (tag) => {
      expect(isInteractiveTagOrRole(tag, null)).toBe(true)
    },
  )

  it("is case-insensitive on the tag name", () => {
    expect(isInteractiveTagOrRole("button", null)).toBe(true)
  })

  it.each(["radio", "checkbox", "button", "link", "switch", "tab", "menuitem"])(
    "treats role=%s as interactive regardless of tag",
    (role) => {
      expect(isInteractiveTagOrRole("DIV", role)).toBe(true)
    },
  )

  it("is false for a plain non-interactive tag with no role", () => {
    expect(isInteractiveTagOrRole("DIV", null)).toBe(false)
  })

  // Documents the known asymmetry rather than silently having it: this form
  // has no signature room for an attribute-only check, so a contenteditable
  // or tabindex-only element reads as non-interactive here even though
  // `.closest(GESTURE_INTERACTIVE_SELECTOR)` on the live node would catch
  // it. Every current call site but `quizSwipe.ts`'s pure decision goes
  // through `.closest()` directly and is unaffected.
  it("cannot see contenteditable or tabindex — no tag/role expresses either", () => {
    expect(isInteractiveTagOrRole("DIV", null)).toBe(false)
  })
})
