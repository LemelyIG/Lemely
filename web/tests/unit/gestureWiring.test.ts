import { describe, expect, it } from "vitest"
import fs from "node:fs"
import path from "node:path"
import { stripComments } from "./support/jsxSource"

/*
 * Task 6 (B4b) · source-text pins that every screen this task touches
 * actually wires the gesture it claims to, and — the part that matters more
 * — that nothing pre-existing was removed to make room for it. Read as text
 * (`stripComments` + `indexOf`/`toContain`), not by rendering: this repo's
 * unit suite runs under Node with no jsdom (`vitest.config.ts`, D3.20), so a
 * component tree or a real pointer gesture cannot be produced here — that
 * coverage lives in `e2e/native-feel.spec.ts` (Task 12). What this file can
 * and does pin is the wiring itself: the right hook imported, the right
 * pure decision function used, and every visible control's label still in
 * the source.
 */

const ROOT = path.join(import.meta.dirname, "..", "..")

function sourceOf(relative: string): string {
  return stripComments(fs.readFileSync(path.join(ROOT, relative), "utf8"))
}

describe("FlashcardReview.tsx — swipe reveal/grade is additive to the existing controls", () => {
  const src = sourceOf("src/portals/student/screens/flashcards/FlashcardReview.tsx")

  it("imports useDragGesture and flashcardSwipeAction", () => {
    expect(src).toContain("useDragGesture")
    expect(src).toContain("flashcardSwipeAction")
  })

  it("still has the Reveal answer button and isRevealKey's keyboard path", () => {
    expect(src).toContain("Reveal answer")
    expect(src).toContain("isRevealKey")
  })

  it("still has all four grade button labels", () => {
    for (const label of ["Again", "Hard", "Good", "Easy"]) {
      expect(src).toContain(label)
    }
  })
})

describe("nav-drawer.tsx — drag-dismiss is additive to the existing close controls", () => {
  const src = sourceOf("src/components/ui/nav-drawer.tsx")

  it("imports useDragGesture and reads --lm-dir for RTL", () => {
    expect(src).toContain("useDragGesture")
    expect(src).toContain("--lm-dir")
  })

  it("still has the Escape/backdrop/close-button paths untouched", () => {
    expect(src).toContain("Escape")
    expect(src).toContain("Close navigation")
  })

  // Issue #246/#247, opus-review finding: the assertion above only pins that
  // the string "Close navigation" still exists somewhere in the file — it
  // passed even while the button itself was unreachable, because
  // `startFilter` armed the drag-dismiss gesture on a tap anywhere outside
  // `.lm-scroll`, including the header button, and `useDragGesture` captured
  // the pointer and swallowed the click before `onClick` ever ran. A
  // Node-only source-text test cannot execute a pointer gesture (no jsdom,
  // `vitest.config.ts`, D3.20) or observe a real `click` event, so it cannot
  // prove the button *works* — that proof is `e2e/native-feel.spec.ts`'s
  // Assertion 8, which clicks this exact button and asserts the dialog
  // closes. What this test CAN and now does prove is the specific thing that
  // was missing: that `startFilter` actually excludes every interactive
  // control, not just the scroll list, by pinning the shared exemption list
  // inside `startFilter`'s own source window rather than anywhere in the
  // file. A regression that silently drops this check (as the original code
  // did, having only `.lm-scroll`) fails here without needing a browser.
  it("startFilter excludes every GESTURE_INTERACTIVE_SELECTOR match, not just .lm-scroll", () => {
    expect(src).toContain("GESTURE_INTERACTIVE_SELECTOR")
    const startFilterAt = src.indexOf("startFilter")
    expect(startFilterAt, "no startFilter found in nav-drawer.tsx").toBeGreaterThan(-1)
    const window = src.slice(startFilterAt, startFilterAt + 300)
    expect(window).toContain(".lm-scroll")
    expect(window).toContain("GESTURE_INTERACTIVE_SELECTOR")
  })
})

describe("edge-swipe-back.tsx — the edge-swipe gesture excludes interactive controls", () => {
  const src = sourceOf("src/components/edge-swipe-back.tsx")

  // Same issue, same mechanism, found in the same review pass:
  // `startFilter` here gated purely on `clientX` against the edge zone, with
  // no interactive-element exemption at all, and `rootRef` is
  // `document.documentElement` — so in a standalone PWA, any control
  // rendered inside the leading (or trailing, under RTL) 24px strip anywhere
  // in the app (the first `BottomNav` item, a full-bleed row's own link) had
  // its tap swallowed the same way. Same limitation as the nav-drawer test
  // above applies: this pins the wiring, not the click; there is no e2e
  // coverage of this gesture at all (standalone-PWA-only, `native-feel.spec.ts`'s
  // own describe blocks do not emulate `display-mode: standalone`), which is
  // a real gap this fix does not close — flagged rather than silently
  // left, since `e2e/*` is read-only here.
  it("startFilter excludes every GESTURE_INTERACTIVE_SELECTOR match before the edge-zone check", () => {
    expect(src).toContain("GESTURE_INTERACTIVE_SELECTOR")
    const startFilterAt = src.indexOf("startFilter")
    expect(startFilterAt, "no startFilter found in edge-swipe-back.tsx").toBeGreaterThan(-1)
    const window = src.slice(startFilterAt, startFilterAt + 1400)
    expect(window).toContain("GESTURE_INTERACTIVE_SELECTOR")
    expect(window).toContain("EDGE_ZONE_PX")
  })
})

describe("QuizTaker.tsx — page-turn swipe flushes autosave before navigating, and locks in the last 60s", () => {
  const src = sourceOf("src/components/quiz/QuizTaker.tsx")

  it("imports quizSwipeAllowed", () => {
    expect(src).toContain("quizSwipeAllowed")
  })

  it("calls flushPendingSaves() inside the drag commit handler, not just at submit", () => {
    const onCommitAt = src.indexOf("onCommit")
    expect(onCommitAt, "no onCommit handler found in QuizTaker.tsx").toBeGreaterThan(-1)
    const window = src.slice(onCommitAt, onCommitAt + 400)
    expect(window).toContain("flushPendingSaves")
  })

  it("still has the Previous and Next buttons", () => {
    expect(src).toContain("Previous")
    expect(src).toContain("Next")
  })
})

describe("Pull-to-refresh — Notifications, Announcements and Overview all wire usePullToRefresh", () => {
  const files = [
    "src/portals/student/screens/Notifications.tsx",
    "src/portals/student/screens/Announcements.tsx",
    "src/portals/student/screens/Overview.tsx",
  ]

  it.each(files)("%s imports usePullToRefresh and renders PullIndicator", (relative) => {
    const src = sourceOf(relative)
    expect(src).toContain("usePullToRefresh")
    expect(src).toContain("PullIndicator")
  })
})

describe("Long-press menus — question-row, Notifications and FlashcardDecks all wire useLongPress + Popover", () => {
  const files = [
    "src/components/ui/question-row.tsx",
    "src/portals/student/screens/Notifications.tsx",
    "src/portals/student/screens/flashcards/FlashcardDecks.tsx",
  ]

  it.each(files)("%s imports useLongPress and Popover", (relative) => {
    const src = sourceOf(relative)
    expect(src).toContain("useLongPress")
    expect(src).toContain("Popover")
  })

  it("question-row.tsx gains optional practiceHref/onShare props, not a required rewrite", () => {
    const src = sourceOf("src/components/ui/question-row.tsx")
    expect(src).toContain("practiceHref?")
    expect(src).toContain("onShare?")
  })

  it("FlashcardDecks.tsx has no Rename affordance — no deck rename endpoint exists", () => {
    const src = sourceOf("src/portals/student/screens/flashcards/FlashcardDecks.tsx")
    expect(src).not.toContain("Rename")
  })

  it("FlashcardDecks.tsx's long-press menu still routes through the existing delete-confirm flow", () => {
    const src = sourceOf("src/portals/student/screens/flashcards/FlashcardDecks.tsx")
    expect(src).toContain("setDeckPendingDelete")
  })
})
