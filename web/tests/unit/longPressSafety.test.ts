import { describe, expect, it } from "vitest"
import fs from "node:fs"
import path from "node:path"
import { stripComments } from "./support/jsxSource"

/*
 * Review fix pass over Tasks 4-6 · H6. The long-press hook leaked its hold
 * timer past unmount, swallowed mouse right-clicks without replacing the
 * native menu, let the click that follows a fired hold toggle the menu shut
 * again, and — the blocking one — left `question-row`'s "Practice this
 * topic" reachable *only* by holding, which no keyboard can do (WCAG 2.1.1,
 * and 2.5.1 for the path-or-timing gesture). The pure halves live in
 * `longPressMath` and are unit-tested directly; what this file pins is the
 * wiring, which the Node-only runner (`vitest.config.ts`, D3.20) cannot
 * reach by rendering.
 */

const ROOT = path.join(import.meta.dirname, "..", "..")

function sourceOf(relative: string): string {
  return stripComments(fs.readFileSync(path.join(ROOT, relative), "utf8"))
}

describe("H6 — long-press is cleaned up, keyboard-reachable and ARIA-wired", () => {
  const hook = sourceOf("src/lib/gestures/useLongPress.ts")

  it("clears its pending timer on unmount", () => {
    expect(hook).toContain("useEffect")
    expect(hook).toMatch(/useEffect\(\s*\(\)\s*=>\s*\(\)\s*=>/)
  })

  it("defers the start decision and the contextmenu decision to longPressMath", () => {
    expect(hook).toContain("shouldStartLongPress")
    expect(hook).toContain("shouldSuppressContextMenu")
  })

  it("exposes a capture-phase click suppressor for the click that follows a fired press", () => {
    expect(hook).toContain("onClickCapture")
  })

  it("question-row.tsx offers a non-gesture path to the same menu (WCAG 2.1.1 / 2.5.1)", () => {
    const src = sourceOf("src/components/ui/question-row.tsx")
    expect(src).toContain("More actions")
    expect(src).toContain("triggerProps")
    // The gesture-only item is the one the review flagged: it must now also
    // be reachable from a real, focusable control.
    expect(src).toContain("Practice this topic")
  })

  it.each([
    "src/components/ui/question-row.tsx",
    "src/portals/student/screens/Notifications.tsx",
    "src/portals/student/screens/flashcards/FlashcardDecks.tsx",
  ])("%s wires the popover's triggerProps instead of discarding them", (relative) => {
    const src = sourceOf(relative)
    // `renderTrigger={() => ...}` — the argument thrown away — is the defect.
    expect(src).toMatch(/renderTrigger=\{\(\{ triggerProps \}\)/)
    // …and the trigger element has to actually receive them, either spread
    // whole (question-row's own button) or picked apart minus `onClick`
    // (a row where a plain tap must not open the menu).
    expect(src).toMatch(/\{\.\.\.triggerProps\}|triggerProps\.ref/)
  })

  it.each([
    "src/components/ui/question-row.tsx",
    "src/portals/student/screens/Notifications.tsx",
    "src/portals/student/screens/flashcards/FlashcardDecks.tsx",
  ])("%s spreads the whole long-press handler set, click suppressor included", (relative) => {
    const src = sourceOf(relative)
    // `onClickCapture` reaches the element through this spread; cherry-picking
    // individual handlers would silently drop it and let the click that
    // follows a fired hold toggle the freshly-opened menu shut again.
    expect(src).toMatch(/\{\.\.\.[^}\n]*longPress/)
  })
})
