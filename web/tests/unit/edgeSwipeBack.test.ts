import { describe, expect, it } from "vitest"
import { edgeSwipeDecision } from "@/lib/nav/edgeSwipeBack"

/*
 * Packet B3 (Task 4) · edge-swipe-back is standalone-only (a browser tab
 * keeps the URL bar's own back gesture) and only commits from the
 * inline-start 24px edge, so a drag starting mid-screen (e.g. dismissing a
 * drawer, paging a quiz) is never mistaken for it.
 */

const BASE = { startX: 12, dx: 40, dy: 0, viewportWidth: 375, standalone: true, dir: 1 as const }

describe("edgeSwipeDecision", () => {
  it("is none in a browser tab even from the edge with a committing drag", () => {
    expect(edgeSwipeDecision({ ...BASE, standalone: false })).toBe("none")
  })

  it("is back for a standalone drag committing from the inline-start edge", () => {
    expect(edgeSwipeDecision(BASE)).toBe("back")
  })

  it("is none when the drag starts past the 24px edge zone", () => {
    expect(edgeSwipeDecision({ ...BASE, startX: 30 })).toBe("none")
  })

  it("is back for an RTL drag from the inline-start edge (viewport's right side)", () => {
    expect(
      edgeSwipeDecision({
        startX: 365,
        dx: -40,
        dy: 0,
        viewportWidth: 375,
        standalone: true,
        dir: -1,
      }),
    ).toBe("back")
  })

  it("is none when the drag moves toward the edge instead of away from it", () => {
    expect(edgeSwipeDecision({ ...BASE, dx: -40 })).toBe("none")
  })

  it("is none when the drag doesn't move away from the edge at all (dx: 0)", () => {
    expect(edgeSwipeDecision({ ...BASE, dx: 0 })).toBe("none")
  })

  it("is none exactly at the 24px edge boundary's far side", () => {
    expect(edgeSwipeDecision({ ...BASE, startX: 25 })).toBe("none")
  })
})
