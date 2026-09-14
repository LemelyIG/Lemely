import { describe, expect, it } from "vitest"
import fs from "node:fs"
import path from "node:path"
import { stripComments } from "./support/jsxSource"

/*
 * Review fix pass over Tasks 4-6 · source-text pins for the four gesture
 * defects an Opus review found. None of these hooks can be mounted here (this
 * suite runs under Node with no jsdom, `vitest.config.ts`, D3.20), so the
 * pure halves of each fix live in `dragMath`/`pullMath`/`longPressMath` and
 * are unit-tested directly; what this file pins is the wiring that decides
 * *which element* each gesture touches and *what it puts back* when it lets
 * go — the part that no pure function can see and no browser test exists to
 * cover in this sandbox.
 */

const ROOT = path.join(import.meta.dirname, "..", "..")

function sourceOf(relative: string): string {
  return stripComments(fs.readFileSync(path.join(ROOT, relative), "utf8"))
}

const PULL_SCREENS = [
  "src/portals/student/screens/Notifications.tsx",
  "src/portals/student/screens/Announcements.tsx",
  "src/portals/student/screens/Overview.tsx",
]

describe("C2 — pull-to-refresh never transforms the document root", () => {
  it.each(PULL_SCREENS)("%s passes a real element ref, not document.documentElement", (relative) => {
    const src = sourceOf(relative)
    expect(src).not.toContain("document.documentElement")
  })

  it.each(PULL_SCREENS)("%s attaches that ref to a rendered element", (relative) => {
    const src = sourceOf(relative)
    expect(src).toMatch(/ref=\{pullSurfaceRef\}/)
  })

  it("usePullToRefresh clamps the imperative transform to a downward pull", () => {
    const src = sourceOf("src/lib/gestures/usePullToRefresh.ts")
    expect(src).toContain('transformClamp: "positive"')
  })

  it("useDragGesture applies that clamp to the transform it writes", () => {
    const src = sourceOf("src/lib/gestures/useDragGesture.ts")
    expect(src).toContain("clampDelta")
    expect(src).toContain("transformClamp")
  })
})

describe("C3 — the edge-swipe zone and the pull zone are disjoint", () => {
  it("usePullToRefresh refuses a drag that starts in either edge strip", () => {
    const src = sourceOf("src/lib/gestures/usePullToRefresh.ts")
    expect(src).toContain("pullStartAllowed")
    expect(src).toContain("EDGE_ZONE_PX")
  })

  it("EdgeSwipeBack still owns the edge strip itself", () => {
    const src = sourceOf("src/components/edge-swipe-back.tsx")
    expect(src).toContain("EDGE_ZONE_PX")
  })
})

describe("H5 — a drag cleans up its own imperative state, not just its listeners", () => {
  const src = sourceOf("src/lib/gestures/useDragGesture.ts")

  it("the effect cleanup aborts an in-flight drag rather than only detaching", () => {
    const cleanupAt = src.lastIndexOf("return () => {")
    expect(cleanupAt, "no effect cleanup found in useDragGesture.ts").toBeGreaterThan(-1)
    const cleanup = src.slice(cleanupAt)
    expect(cleanup).toContain("abortDrag")
  })

  it("aborting clears transform, transition and pointer capture", () => {
    const abortAt = src.indexOf("function abortDrag")
    expect(abortAt, "no abortDrag() found in useDragGesture.ts").toBeGreaterThan(-1)
    const body = src.slice(abortAt, abortAt + 700)
    expect(body).toContain("style.transform")
    expect(body).toContain("style.transition")
    expect(body).toContain("releasePointerCapture")
  })

  it("springBack registers its transitionend listener once and has a fallback", () => {
    const springAt = src.indexOf("function springBack")
    expect(springAt, "no springBack() found in useDragGesture.ts").toBeGreaterThan(-1)
    const body = src.slice(springAt, springAt + 1400)
    expect(body).toContain("once: true")
    expect(body).toContain("setTimeout")
  })

  it("springBack does not leave style.transition set after a non-moving tap", () => {
    const springAt = src.indexOf("function springBack")
    const body = src.slice(springAt, springAt + 1400)
    // The zero-distance case: no transform was ever written, so no
    // `transitionend` will ever fire — the transition has to be cleared
    // synchronously instead of waiting for an event that cannot arrive.
    expect(body).toMatch(/if \(!t\.style\.transform\)/)
  })
})

describe("MEDIUM — horizontal drag surfaces declare touch-action", () => {
  const HORIZONTAL = [
    "src/components/quiz/QuizTaker.tsx",
    "src/portals/student/screens/flashcards/FlashcardReview.tsx",
    "src/components/ui/nav-drawer.tsx",
  ]

  it("useDragGesture can own the touch-action itself", () => {
    const src = sourceOf("src/lib/gestures/useDragGesture.ts")
    expect(src).toContain("touchAction")
  })

  it.each(HORIZONTAL)("%s sets pan-y on its drag surface", (relative) => {
    const src = sourceOf(relative)
    expect(src).toContain('touchAction: "pan-y"')
  })
})
