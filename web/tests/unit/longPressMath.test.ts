import { describe, expect, it } from "vitest"
import {
  longPressDecision,
  shouldStartLongPress,
  shouldSuppressContextMenu,
} from "@/lib/gestures/longPressMath"

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

/*
 * H6 fix · the hook used to start its hold timer for any pointer button and
 * to `preventDefault()` every `contextmenu` while a press was in flight, so a
 * mouse right-click lost the browser's own menu and got nothing in its place.
 * Both decisions are pure, and both are pinned here.
 */
describe("shouldStartLongPress", () => {
  it("starts on a touch or pen press (button 0)", () => {
    expect(shouldStartLongPress({ button: 0, startedOnInteractive: false })).toBe(true)
  })

  it("starts on a primary mouse press", () => {
    expect(shouldStartLongPress({ button: 0, startedOnInteractive: false })).toBe(true)
  })

  it("never starts on a secondary or middle button — those are the browser's", () => {
    expect(shouldStartLongPress({ button: 1, startedOnInteractive: false })).toBe(false)
    expect(shouldStartLongPress({ button: 2, startedOnInteractive: false })).toBe(false)
  })

  it("never starts on an interactive descendant that owns its own click", () => {
    expect(shouldStartLongPress({ button: 0, startedOnInteractive: true })).toBe(false)
  })
})

describe("shouldSuppressContextMenu", () => {
  it("suppresses the native menu for a touch long-press, which opens our own", () => {
    expect(shouldSuppressContextMenu("touch", true)).toBe(true)
    expect(shouldSuppressContextMenu("pen", true)).toBe(true)
  })

  it("never suppresses a mouse right-click — nothing replaces the browser's menu", () => {
    expect(shouldSuppressContextMenu("mouse", true)).toBe(false)
  })

  it("never suppresses when no press is in flight", () => {
    expect(shouldSuppressContextMenu("touch", false)).toBe(false)
    expect(shouldSuppressContextMenu("mouse", false)).toBe(false)
  })
})
