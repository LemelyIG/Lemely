import { describe, expect, it } from "vitest"

import { stabilityDecision } from "@/lib/scanner/stability"

describe("stabilityDecision", () => {
  it("captures once the frame has stayed steady for the required window", () => {
    expect(stabilityDecision([1, 1, 1], true)).toBe("capture")
  })

  it("holds when a recent frame moved (delta above maxDelta)", () => {
    expect(stabilityDecision([1, 9, 1], true)).toBe("hold")
  })

  it("holds when no document quad was found, even if the frame is steady", () => {
    expect(stabilityDecision([1, 1, 1], false)).toBe("hold")
  })

  it("holds until enough frames have accumulated", () => {
    expect(stabilityDecision([1], true)).toBe("hold")
    expect(stabilityDecision([1, 1], true)).toBe("hold")
    expect(stabilityDecision([], true)).toBe("hold")
  })

  it("only looks at the most recent window, not the whole history", () => {
    // An old spike, long since settled, must not keep holding forever.
    expect(stabilityDecision([50, 1, 1, 1], true)).toBe("capture")
  })

  it("honours custom maxDelta and frames options", () => {
    expect(stabilityDecision([3, 3], true, { maxDelta: 5, frames: 2 })).toBe("capture")
    expect(stabilityDecision([3, 3], true, { maxDelta: 2, frames: 2 })).toBe("hold")
  })
})
