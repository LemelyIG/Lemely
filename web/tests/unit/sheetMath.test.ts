import { describe, expect, it } from "vitest"
import { DISMISS_FRACTION, FLING_PX_PER_MS, sheetRelease, swipeBackRelease } from "@/lib/gestures/sheetMath"

const base = { height: 400, detent: "large" as const, detents: ["medium", "large"] as const, dismissible: true }

describe("sheetRelease (D10)", () => {
  it("a short slow drag snaps back to the current detent", () => {
    expect(sheetRelease({ ...base, dy: 40, velocity: 0.1 })).toEqual({ kind: "snap", detent: "large" })
  })
  it("past a quarter of the height dismisses from the lowest detent", () => {
    expect(sheetRelease({ ...base, detent: "medium", dy: 400 * DISMISS_FRACTION + 1, velocity: 0.1 })).toEqual({ kind: "dismiss" })
  })
  it("a downward drag from large steps to medium before it dismisses", () => {
    expect(sheetRelease({ ...base, dy: 160, velocity: 0.1 })).toEqual({ kind: "snap", detent: "medium" })
  })
  it("a fast fling down dismisses even when short", () => {
    expect(sheetRelease({ ...base, detent: "medium", dy: 20, velocity: FLING_PX_PER_MS + 0.1 })).toEqual({ kind: "dismiss" })
  })
  it("dragging up from medium goes to large", () => {
    expect(sheetRelease({ ...base, detent: "medium", dy: -120, velocity: -0.2 })).toEqual({ kind: "snap", detent: "large" })
  })
  it("a non-dismissible sheet never dismisses", () => {
    expect(sheetRelease({ ...base, detent: "medium", dy: 999, velocity: 3, dismissible: false })).toEqual({ kind: "snap", detent: "medium" })
  })
  it("a content-fit sheet has one detent", () => {
    expect(sheetRelease({ ...base, detents: ["content"], detent: "content", dy: 50, velocity: 0 })).toEqual({ kind: "snap", detent: "content" })
  })
})

describe("swipeBackRelease (brief §6: 35% or a fast fling)", () => {
  it.each([
    [136, 0.1, 390, "commit"],
    [100, 0.1, 390, "cancel"],
    [40, 0.8, 390, "commit"],
    [-50, -0.9, 390, "cancel"],
  ] as const)("dx %i v %f w %i -> %s", (dx, velocity, width, want) => {
    expect(swipeBackRelease({ dx, velocity, width })).toBe(want)
  })
})
