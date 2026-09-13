import { describe, expect, it } from "vitest"
import { longPressDecision } from "@/lib/gestures/longPressMath"

/*
 * Task 5 (B4a) · the pure decision `useLongPress` reduces a held pointer to:
 * keep waiting, fire the long-press callback, or cancel because the pointer
 * moved too far (a scroll or drag, not a hold) or the press started on an
 * interactive descendant that should keep its own click/tap behaviour. Kept
 * pure and tested directly, same reasoning as `pullMath.test.ts`.
 */

const BASE = { holdMs: 500, moveTolerance: 10, startedOnInteractive: false }

describe("longPressDecision", () => {
  it("waits just before the hold duration with no movement", () => {
    expect(longPressDecision({ ...BASE, elapsedMs: 499, movedPx: 0 })).toBe("wait")
  })

  it("fires once the hold duration elapses with no movement", () => {
    expect(longPressDecision({ ...BASE, elapsedMs: 500, movedPx: 0 })).toBe("fire")
  })

  it("cancels when the pointer moves past the tolerance, even early", () => {
    expect(longPressDecision({ ...BASE, elapsedMs: 200, movedPx: 11 })).toBe("cancel")
  })

  it("cancels a press that started on an interactive descendant", () => {
    expect(
      longPressDecision({ ...BASE, elapsedMs: 500, movedPx: 0, startedOnInteractive: true }),
    ).toBe("cancel")
  })

  it("waits at exactly the movement tolerance", () => {
    expect(longPressDecision({ ...BASE, elapsedMs: 200, movedPx: 10 })).toBe("wait")
  })

  it("fires well past the hold duration with no movement", () => {
    expect(longPressDecision({ ...BASE, elapsedMs: 1200, movedPx: 0 })).toBe("fire")
  })
})
