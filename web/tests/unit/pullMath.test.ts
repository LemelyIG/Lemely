import { describe, expect, it } from "vitest"
import { pullStartAllowed, pullState, usesOwnScrollTop } from "@/lib/gestures/pullMath"

/*
 * Task 5 (B4a) · the pure decision `usePullToRefresh` reduces a vertical
 * drag to: how far along the pull is (0..1, for the indicator) and whether
 * it has travelled far enough to arm a refresh on release. Kept pure and
 * tested directly since `vitest.config.ts` runs this suite under Node with
 * no jsdom (D3.20) — same reasoning as `dragMath.test.ts`.
 */

describe("pullState", () => {
  it("is 0 and unarmed regardless of dy when not at the scroll top", () => {
    expect(pullState(80, 72, false)).toEqual({ progress: 0, armed: false })
    expect(pullState(200, 72, false)).toEqual({ progress: 0, armed: false })
  })

  it("is a fraction of the threshold, unarmed, for a partial pull", () => {
    expect(pullState(36, 72, true)).toEqual({ progress: 0.5, armed: false })
  })

  it("is armed and clamped to 1 once the pull passes the threshold", () => {
    expect(pullState(80, 72, true)).toEqual({ progress: 1, armed: true })
  })

  it("is armed at exactly the threshold", () => {
    expect(pullState(72, 72, true)).toEqual({ progress: 1, armed: true })
  })

  it("is 0 and unarmed for a negative dy (pushing up, not pulling down)", () => {
    expect(pullState(-40, 72, true)).toEqual({ progress: 0, armed: false })
  })

  it("is 0 and unarmed at exactly zero movement", () => {
    expect(pullState(0, 72, true)).toEqual({ progress: 0, armed: false })
  })
})

/*
 * C3 fix · `EdgeSwipeBack` listens on `document` for a drag starting in the
 * leading/trailing `EDGE_ZONE_PX` strip, and a pull-to-refresh surface fills
 * the screen underneath it. Both used to accept a touch in the top-left 24px
 * at `scrollY === 0`, so both captured the same pointer and both wrote a
 * `transform`. `pullStartAllowed` is the geometric half of making the two
 * zones disjoint: a pull never starts inside either edge strip.
 */
describe("pullStartAllowed", () => {
  it("rejects a start inside the leading edge strip", () => {
    expect(pullStartAllowed(0, 390, 24)).toBe(false)
    expect(pullStartAllowed(24, 390, 24)).toBe(false)
  })

  it("rejects a start inside the trailing edge strip", () => {
    expect(pullStartAllowed(390, 390, 24)).toBe(false)
    expect(pullStartAllowed(366, 390, 24)).toBe(false)
  })

  it("accepts a start anywhere between the two strips", () => {
    expect(pullStartAllowed(25, 390, 24)).toBe(true)
    expect(pullStartAllowed(195, 390, 24)).toBe(true)
    expect(pullStartAllowed(365, 390, 24)).toBe(true)
  })

  it("is disjoint from the edge-swipe zone in both directions", () => {
    const width = 390
    for (let x = 0; x <= width; x++) {
      const onEdge = x <= 24 || x >= width - 24
      expect(pullStartAllowed(x, width, 24)).toBe(!onEdge)
    }
  })
})

/*
 * C2 fix · the pull surface is now an inner content element, not
 * `document.documentElement`, so "am I at the scroll top?" can no longer be
 * answered by that element's own `scrollTop` — a non-scrolling wrapper
 * reports 0 forever. `usesOwnScrollTop` decides which reading to trust.
 */
describe("usesOwnScrollTop", () => {
  it("is false for a non-scrolling wrapper, whatever its overflow", () => {
    expect(usesOwnScrollTop("visible", 400, 400)).toBe(false)
    expect(usesOwnScrollTop("auto", 400, 400)).toBe(false)
  })

  it("is false for overflowing content that the element does not scroll itself", () => {
    expect(usesOwnScrollTop("visible", 2000, 400)).toBe(false)
  })

  it("is true only for an element that both scrolls and overflows", () => {
    expect(usesOwnScrollTop("auto", 2000, 400)).toBe(true)
    expect(usesOwnScrollTop("scroll", 2000, 400)).toBe(true)
  })
})
