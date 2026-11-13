import { describe, expect, it } from "vitest"
import { BODY_DRAG_SLOP, DISMISS_FRACTION, FLING_PX_PER_MS, bodyDragIntent, releaseVelocity, sheetRelease, swipeBackRelease, trimSamples, type PointerSample } from "@/lib/gestures/sheetMath"

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

describe("releaseVelocity (last 100ms window)", () => {
  it("a slow drag that ends in a flick reads the flick, not the average", () => {
    // 300ms of slow drift (0.05 px/ms), then 40px in the last 50ms.
    const samples: PointerSample[] = [[0, 0], [100, 5], [200, 10], [300, 15], [350, 55]]
    const v = releaseVelocity(samples, 400, 95)
    const average = 95 / 400
    expect(average).toBeLessThan(FLING_PX_PER_MS)
    expect(v).toBeGreaterThan(FLING_PX_PER_MS)
    expect(sheetRelease({ ...base, detent: "medium", dy: 95, velocity: v })).toEqual({ kind: "dismiss" })
  })
  it("a flick that stalls before release reads as slow", () => {
    const samples: PointerSample[] = [[0, 0], [20, 60], [40, 100], [400, 101]]
    expect(Math.abs(releaseVelocity(samples, 500, 101))).toBeLessThan(0.1)
  })
  it("no elapsed time reads as zero", () => {
    expect(releaseVelocity([[10, 5]], 10, 50)).toBe(0)
    expect(releaseVelocity([], 10, 50)).toBe(0)
  })
  it("trimSamples drops samples older than 100ms", () => {
    expect(trimSamples([[0, 0], [150, 1], [200, 2]], 220)).toEqual([[150, 1], [200, 2]])
  })
})

describe("bodyDragIntent (a press that starts in a sheet's body)", () => {
  it("is undecided until the finger passes the slop", () => {
    expect(bodyDragIntent({ scrollTop: 0, dy: 3 })).toBe("undecided")
    expect(bodyDragIntent({ scrollTop: 0, dy: -3 })).toBe("undecided")
  })
  it("a downward move at the top of the body drags the sheet", () => {
    expect(bodyDragIntent({ scrollTop: 0, dy: BODY_DRAG_SLOP })).toBe("drag")
  })
  it("an upward move at the top is the body's own scroll", () => {
    expect(bodyDragIntent({ scrollTop: 0, dy: -20 })).toBe("scroll")
  })
  it("a scrolled body never drags the sheet, whichever way the finger goes", () => {
    expect(bodyDragIntent({ scrollTop: 1, dy: 40 })).toBe("scroll")
    expect(bodyDragIntent({ scrollTop: 120, dy: -40 })).toBe("scroll")
  })
})
