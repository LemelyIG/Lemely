import { describe, expect, it } from "vitest"
import type { ReviewItemPoint } from "@/lib/teacherTypes"
import {
  breakdownOf,
  canStep,
  deltaLine,
  initialMarkState,
  isBlocked,
  markPointsFrom,
  notePlaceholder,
  orBefore,
  poolHeader,
  primaryActionLabel,
  resolveBody,
  stepDown,
  stepUp,
  toggleTick,
  totalOf,
} from "@/portals/teacher/screens/review/markModel"

function wire(over: Partial<ReviewItemPoint> & { markPointId: string }): ReviewItemPoint {
  return {
    pointText: over.markPointId,
    awarded: false,
    studentSelfmark: null,
    studentEvidence: null,
    evidenceVerdict: null,
    verdict: null,
    evidenceSpan: "",
    ecfApplied: false,
    rationale: null,
    ordinal: 0,
    markType: "M",
    tariff: 1,
    groupKey: null,
    groupMaxMarks: null,
    ...over,
  }
}

// The mock's Q4(b): M1 M1 [A1 OR B1] M1 A1, max 5, Lemely gave 4 (p1 p2 p4 p5).
const Q4 = markPointsFrom([
  wire({ markPointId: "p1", awarded: true, ordinal: 0 }),
  wire({ markPointId: "p2", awarded: true, ordinal: 1 }),
  wire({ markPointId: "p3", markType: "A", groupKey: "alt:2", groupMaxMarks: 1, ordinal: 2 }),
  wire({ markPointId: "p4", markType: "B", groupKey: "alt:2", groupMaxMarks: 1, awarded: true, ordinal: 3 }),
  wire({ markPointId: "p5", awarded: true, ordinal: 4 }),
  wire({ markPointId: "p6", markType: "A", ordinal: 5 }),
])

describe("markPointsFrom", () => {
  it("codes points like the scheme and carries verdict notes", () => {
    const [p] = markPointsFrom([
      wire({ markPointId: "p1", verdict: "unverifiable", evidenceSpan: "a = 5", ecfApplied: true }),
    ])
    expect(p.code).toBe("M1")
    expect(p.verdictLabel).toBe("Couldn't confirm")
    expect(p.note).toBe("“a = 5”")
    expect(p.ecf).toBe(true)
    const [w] = markPointsFrom([wire({ markPointId: "x", verdict: "withheld", rationale: "No unit." })])
    expect(w.verdictLabel).toBe("Judged absent")
    expect(w.note).toBe("No unit.")
    const [n] = markPointsFrom([wire({ markPointId: "p9", markType: null })])
    expect(n.code).toBe("p9")
  })
})

describe("totals", () => {
  it("starts at Lemely's own mark", () => {
    const s = initialMarkState(Q4, 4)
    expect(s.ticked).toEqual(["p1", "p2", "p4", "p5"])
    expect(totalOf(Q4, s, 5, 4)).toBe(4)
  })
  it("recomputes from ticks once touched, and caps either/or groups", () => {
    let s = initialMarkState(Q4, 4)
    s = toggleTick(Q4, s, "p6", 5)
    expect(totalOf(Q4, s, 5, 4)).toBe(5)
  })
  it("blocks the other branch of an either/or", () => {
    const s = initialMarkState(Q4, 4)
    expect(isBlocked(Q4, s, "p3", 5)).toBe(true)
    expect(toggleTick(Q4, s, "p3", 5)).toBe(s)
  })
  it("blocks unticked points once the question maximum is reached", () => {
    let s = initialMarkState(Q4, 4)
    s = toggleTick(Q4, s, "p6", 5)
    s = toggleTick(Q4, s, "p4", 5)
    expect(isBlocked(Q4, s, "p3", 5)).toBe(false)
    s = toggleTick(Q4, s, "p3", 5)
    expect(totalOf(Q4, s, 5, 4)).toBe(5)
  })
  it("caps pools at the group maximum", () => {
    const pool = markPointsFrom([
      wire({ markPointId: "a", groupKey: "pool:1", groupMaxMarks: 2 }),
      wire({ markPointId: "b", groupKey: "pool:1", groupMaxMarks: 2 }),
      wire({ markPointId: "c", groupKey: "pool:1", groupMaxMarks: 2 }),
    ])
    let s = initialMarkState(pool, 0)
    s = toggleTick(pool, s, "a", 3)
    s = toggleTick(pool, s, "b", 3)
    expect(totalOf(pool, s, 3, 0)).toBe(2)
    expect(isBlocked(pool, s, "c", 3)).toBe(true)
    expect(poolHeader(pool, 0)).toBe("Up to 2 marks from these")
    expect(poolHeader(pool, 1)).toBeNull()
  })
})

describe("stepper", () => {
  it("adds the next eligible point and removes the last ticked", () => {
    let s = initialMarkState(Q4, 4)
    s = stepUp(Q4, s, 5)
    expect(s.ticked.at(-1)).toBe("p6")
    expect(totalOf(Q4, s, 5, 4)).toBe(5)
    expect(canStep(Q4, s, 5, 4)).toEqual({ down: true, up: false })
    s = stepDown(Q4, s)
    s = stepDown(Q4, s)
    expect(totalOf(Q4, s, 5, 4)).toBe(3)
  })
  it("steps a raw number when there are no points", () => {
    let s = initialMarkState([], 1)
    expect(totalOf([], s, 3, 1)).toBe(1)
    s = stepUp([], s, 3)
    s = stepUp([], s, 3)
    s = stepUp([], s, 3)
    expect(totalOf([], s, 3, 1)).toBe(3)
    expect(canStep([], s, 3, 1)).toEqual({ down: true, up: false })
    s = stepDown([], stepDown([], stepDown([], stepDown([], s))))
    expect(totalOf([], s, 3, 1)).toBe(0)
    expect(canStep([], s, 3, 1)).toEqual({ down: false, up: true })
  })
})

describe("copy", () => {
  it("states the change against Lemely", () => {
    expect(deltaLine(4, 4)).toBe("as marked by Lemely")
    expect(deltaLine(5, 4)).toBe("+1 from Lemely")
    expect(deltaLine(2, 4)).toBe("−2 from Lemely")
    expect(primaryActionLabel(4, 5, 4)).toBe("Accept 4/5")
    expect(primaryActionLabel(3, 5, 4)).toBe("Save 3/5")
    expect(notePlaceholder(false)).toBe("Note for your records (optional)")
    expect(notePlaceholder(true)).toBe("Note to student (optional)")
  })
  it("draws OR between members of an either/or", () => {
    expect(orBefore(Q4, 3)).toBe(true)
    expect(orBefore(Q4, 2)).toBe(false)
    expect(orBefore(Q4, 4)).toBe(false)
  })
})

describe("resolve body", () => {
  it("accepts as-is with an internal note when unchanged", () => {
    const s = initialMarkState(Q4, 4)
    expect(resolveBody({ points: Q4, state: s, max: 5, lemely: 4, note: " ok ", canAdjust: true })).toEqual({ note: "ok" })
  })
  it("overrides with a tick-derived breakdown and a student note when changed", () => {
    const s = stepDown(Q4, initialMarkState(Q4, 4))
    expect(resolveBody({ points: Q4, state: s, max: 5, lemely: 4, note: "", canAdjust: true })).toEqual({
      overrideMarks: 3,
      breakdown: { methodMarks: 2, accuracyMarks: 0, otherMarks: 1, notes: null },
    })
    expect(breakdownOf(Q4, s)).toEqual({ methodMarks: 2, accuracyMarks: 0, otherMarks: 1, notes: null })
  })
  it("never overrides when the item cannot be adjusted (I16)", () => {
    const s = stepDown(Q4, initialMarkState(Q4, 4))
    expect(resolveBody({ points: Q4, state: s, max: 5, lemely: 4, note: "", canAdjust: false })).toEqual({})
  })
  it("sends no breakdown for a raw-number change", () => {
    const s = stepUp([], initialMarkState([], 1), 3)
    expect(resolveBody({ points: [], state: s, max: 3, lemely: 1, note: "", canAdjust: true })).toEqual({ overrideMarks: 2 })
  })
})
