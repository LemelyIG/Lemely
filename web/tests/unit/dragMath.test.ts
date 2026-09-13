import { describe, expect, it } from "vitest"
import { dragProgress, shouldCommitDrag } from "@/lib/gestures/dragMath"

/*
 * Packet B3 (Task 4) · the pure commit/progress math `useDragGesture` (and
 * every gesture built on it — edge-swipe here, pull-to-refresh and the
 * flashcard/quiz/drawer swipes in B4) reduces a drag to a yes/no and a 0..1
 * number. Kept pure and tested directly since `vitest.config.ts` runs this
 * suite under Node with no jsdom (D3.20) — nothing that touches a pointer
 * event or a DOM ref is reachable here, but the decision the hook makes is.
 */

describe("shouldCommitDrag", () => {
  it("commits an x-axis drag past the threshold and dominant over y", () => {
    expect(shouldCommitDrag(11, 5, "x")).toBe(true)
  })

  it("does not commit when y is too close to dominant (not >2x)", () => {
    expect(shouldCommitDrag(11, 6, "x")).toBe(false)
  })

  it("does not commit at exactly the threshold", () => {
    expect(shouldCommitDrag(10, 0, "x")).toBe(false)
  })

  it("mirrors the same rule on the y axis", () => {
    expect(shouldCommitDrag(5, 11, "y")).toBe(true)
    expect(shouldCommitDrag(6, 11, "y")).toBe(false)
    expect(shouldCommitDrag(0, 10, "y")).toBe(false)
  })

  it("is direction-agnostic (negative deltas commit the same as positive)", () => {
    expect(shouldCommitDrag(-11, -5, "x")).toBe(true)
    expect(shouldCommitDrag(-11, 5, "x")).toBe(true)
  })

  it("honours a custom threshold", () => {
    expect(shouldCommitDrag(30, 0, "x", 40)).toBe(false)
    expect(shouldCommitDrag(41, 0, "x", 40)).toBe(true)
  })
})

describe("dragProgress", () => {
  it("is 0 at no movement", () => {
    expect(dragProgress(0, 72)).toBe(0)
  })

  it("is a fraction of the distance for a partial drag", () => {
    expect(dragProgress(36, 72)).toBe(0.5)
  })

  it("clamps at 1 past the full distance", () => {
    expect(dragProgress(200, 72)).toBe(1)
  })

  it("takes the magnitude of a negative delta", () => {
    expect(dragProgress(-36, 72)).toBe(0.5)
  })

  it("clamps at 0 for a non-positive distance", () => {
    expect(dragProgress(10, 0)).toBe(0)
    expect(dragProgress(10, -5)).toBe(0)
  })
})
