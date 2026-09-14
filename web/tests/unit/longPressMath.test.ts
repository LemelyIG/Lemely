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

/*
 * `longPressDecision` used to also decide "fire" (from `elapsedMs >=
 * holdMs`) and take a `startedOnInteractive` flag — both dead weight.
 * `useLongPress.ts`'s own `setTimeout` is the sole arbiter of firing (its
 * callback fires unconditionally at `holdMs`, not gated on this function's
 * say-so), and `startedOnInteractive` was always hardcoded `false` at the
 * only call site (`onPointerMove`): a press that started on an interactive
 * descendant is refused at `onPointerDown` via `shouldStartLongPress`
 * (tested below) and never reaches `onPointerMove`'s state at all. This
 * function's only real job is "has the pointer moved too far to still count
 * as a hold".
 */
describe("longPressDecision", () => {
  it("waits while the pointer stays within the movement tolerance", () => {
    expect(longPressDecision({ movedPx: 0, moveTolerance: 10 })).toBe("wait")
    expect(longPressDecision({ movedPx: 10, moveTolerance: 10 })).toBe("wait")
  })

  it("cancels once the pointer moves past the tolerance", () => {
    expect(longPressDecision({ movedPx: 11, moveTolerance: 10 })).toBe("cancel")
  })
})

/*
 * H6 fix · the hook used to start its hold timer for any pointer button and
 * to `preventDefault()` every `contextmenu` while a press was in flight, so a
 * mouse right-click lost the browser's own menu and got nothing in its place.
 * Both decisions are pure, and both are pinned here.
 */
describe("shouldStartLongPress", () => {
  it("starts on button 0 — touch, pen and a primary mouse press all report it the same way", () => {
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
