import { describe, expect, it } from "vitest"
import type { ReviewItemPoint } from "@/lib/teacherTypes"
import {
  breakdownOf,
  canSave,
  canStep,
  clampNote,
  deltaLine,
  initialMarkState,
  isBlocked,
  type MarkState,
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
    const s = initialMarkState(Q4, 4, 5)
    expect(s.ticked).toEqual(["p1", "p2", "p4", "p5"])
    expect(totalOf(Q4, s, 5)).toBe(4)
  })
  it("recomputes from ticks once touched", () => {
    let s = initialMarkState(Q4, 4, 5)
    s = toggleTick(Q4, s, "p6", 5)
    expect(s.touched).toBe(true)
    expect(totalOf(Q4, s, 5)).toBe(5)
  })
  it("blocks the other branch of an either/or", () => {
    const s = initialMarkState(Q4, 4, 5)
    expect(isBlocked(Q4, s, "p3", 5)).toBe(true)
    expect(toggleTick(Q4, s, "p3", 5)).toBe(s)
  })
  it("caps either/or groups: one member at a time, in either direction", () => {
    let s = initialMarkState(Q4, 4, 5)
    s = toggleTick(Q4, s, "p4", 5)
    expect(s.ticked).toEqual(["p1", "p2", "p5"])
    expect(isBlocked(Q4, s, "p3", 5)).toBe(false)
    s = toggleTick(Q4, s, "p3", 5)
    expect(s.ticked).toEqual(["p1", "p2", "p5", "p3"])
    expect(isBlocked(Q4, s, "p4", 5)).toBe(true)
    expect(toggleTick(Q4, s, "p4", 5)).toBe(s)
    expect(totalOf(Q4, s, 5)).toBe(4)
  })
  it("blocks a second either/or member even when the group cap would allow it", () => {
    const alt = markPointsFrom([
      wire({ markPointId: "x", groupKey: "alt:1", groupMaxMarks: 2, ordinal: 0 }),
      wire({ markPointId: "y", groupKey: "alt:1", groupMaxMarks: 2, ordinal: 1 }),
    ])
    const s = toggleTick(alt, initialMarkState(alt, 0), "x", 5)
    expect(isBlocked(alt, s, "y", 5)).toBe(true)
    expect(toggleTick(alt, s, "y", 5)).toBe(s)
  })
  it("blocks unticked points once the question maximum is reached", () => {
    const three = markPointsFrom([
      wire({ markPointId: "a", ordinal: 0 }),
      wire({ markPointId: "b", ordinal: 1 }),
      wire({ markPointId: "c", ordinal: 2 }),
    ])
    let s = initialMarkState(three, 0)
    s = toggleTick(three, s, "a", 2)
    expect(isBlocked(three, s, "c", 2)).toBe(false)
    s = toggleTick(three, s, "b", 2)
    expect(isBlocked(three, s, "c", 2)).toBe(true)
    expect(toggleTick(three, s, "c", 2)).toBe(s)
    expect(isBlocked(three, s, "c", null)).toBe(false)
    s = toggleTick(three, s, "a", 2)
    expect(isBlocked(three, s, "c", 2)).toBe(false)
    expect(toggleTick(three, s, "c", 2).ticked).toEqual(["b", "c"])
  })
  it("ignores an unknown point id rather than counting it as blocked", () => {
    const s = initialMarkState(Q4, 4, 5)
    expect(isBlocked(Q4, s, "nope", 5)).toBe(false)
    expect(toggleTick(Q4, s, "nope", 5)).toBe(s)
  })
  it("clamps the total to the maximum", () => {
    const three = markPointsFrom([
      wire({ markPointId: "a", ordinal: 0 }),
      wire({ markPointId: "b", ordinal: 1 }),
      wire({ markPointId: "c", ordinal: 2 }),
    ])
    const over: MarkState = { ticked: ["a", "b", "c"], touched: true, raw: 0 }
    expect(totalOf(three, over, 2)).toBe(2)
    expect(totalOf(three, over, null)).toBe(3)
    expect(totalOf([], { ticked: [], touched: true, raw: 9 }, 3)).toBe(3)
    expect(totalOf([], { ticked: [], touched: true, raw: -2 }, 3)).toBe(0)
    expect(totalOf([], { ticked: [], touched: true, raw: 9 }, null)).toBe(9)
  })
  it("derives ticks that add up to Lemely's total when they disagree at load", () => {
    const three = markPointsFrom([
      wire({ markPointId: "a", awarded: true, ordinal: 0 }),
      wire({ markPointId: "b", ordinal: 1 }),
      wire({ markPointId: "c", ordinal: 2 }),
    ])
    const s = initialMarkState(three, 2, 3)
    expect(s.ticked).toEqual(["a", "b"])
    expect(totalOf(three, s, 3)).toBe(2)
    expect(initialMarkState(three, 0, 3).ticked).toEqual([])
    expect(initialMarkState(three, null, 3).ticked).toEqual(["a"])
    expect(initialMarkState(three, null, 3).raw).toBe(0)
    expect(initialMarkState(three, 2, 3).raw).toBe(2)
  })
  it("clamps an untouched Lemely mark above the maximum", () => {
    const three = markPointsFrom([
      wire({ markPointId: "a", awarded: true, ordinal: 0 }),
      wire({ markPointId: "b", awarded: true, ordinal: 1 }),
      wire({ markPointId: "c", awarded: true, ordinal: 2 }),
    ])
    const s = initialMarkState(three, 3, 2)
    expect(totalOf(three, s, 2)).toBe(2)
    expect(totalOf([], initialMarkState([], 9, 3), 3)).toBe(3)
    expect(totalOf([], initialMarkState([], -4, 3), 3)).toBe(0)
  })
  it("counts a tariff-2 point at its tariff and respects the group cap", () => {
    const pool = markPointsFrom([
      wire({ markPointId: "t", tariff: 2, groupKey: "pool:1", groupMaxMarks: 3, ordinal: 0 }),
      wire({ markPointId: "u", tariff: 2, groupKey: "pool:1", groupMaxMarks: 3, ordinal: 1 }),
      wire({ markPointId: "v", tariff: 2, groupKey: "pool:2", groupMaxMarks: null, ordinal: 2 }),
      wire({ markPointId: "w", tariff: 2, groupKey: "pool:2", groupMaxMarks: null, ordinal: 3 }),
    ])
    expect(pool[0].code).toBe("M2")
    let s = initialMarkState(pool, 0)
    s = toggleTick(pool, s, "t", 10)
    expect(totalOf(pool, s, 10)).toBe(2)
    expect(isBlocked(pool, s, "u", 10)).toBe(false)
    s = toggleTick(pool, s, "u", 10)
    expect(totalOf(pool, s, 10)).toBe(3)
    // Group without its own maximum is capped at one point's tariff.
    s = toggleTick(pool, s, "v", 10)
    expect(isBlocked(pool, s, "w", 10)).toBe(true)
    expect(totalOf(pool, s, 10)).toBe(5)
    expect(poolHeader(pool, 2)).toBe("Up to 2 marks from these")
    expect(poolHeader(markPointsFrom([wire({ markPointId: "q", groupKey: "pool:9", groupMaxMarks: 1 })]), 0)).toBe(
      "Up to 1 mark from these",
    )
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
    expect(totalOf(pool, s, 3)).toBe(2)
    expect(isBlocked(pool, s, "c", 3)).toBe(true)
    expect(poolHeader(pool, 0)).toBe("Up to 2 marks from these")
    expect(poolHeader(pool, 1)).toBeNull()
  })
})

describe("stepper", () => {
  it("moves exactly one mark per step when ticks and tariffs disagree with the total", () => {
    // tariff-2 first, a tariff-1 behind it: stepping must never jump by 2 or stall.
    const pts = markPointsFrom([
      wire({ markPointId: "t", tariff: 2, ordinal: 0 }),
      wire({ markPointId: "u", ordinal: 1 }),
      wire({ markPointId: "v", ordinal: 2 }),
    ])
    let s = initialMarkState(pts, 0, 4)
    const seen = [totalOf(pts, s, 4)]
    for (let i = 0; i < 4; i++) {
      s = stepUp(pts, s, 4)
      seen.push(totalOf(pts, s, 4))
    }
    expect(seen).toEqual([0, 1, 2, 3, 4])
    expect(canStep(pts, s, 4)).toEqual({ down: true, up: false })
    for (let i = 3; i >= 0; i--) {
      s = stepDown(pts, s, 4)
      expect(totalOf(pts, s, 4)).toBe(i)
    }
    expect(canStep(pts, s, 4)).toEqual({ down: false, up: true })
  })
  it("has no dead step when Lemely's ticks disagree with its total", () => {
    const pts = markPointsFrom([
      wire({ markPointId: "a", awarded: true, ordinal: 0 }),
      wire({ markPointId: "b", ordinal: 1 }),
      wire({ markPointId: "c", ordinal: 2 }),
    ])
    let s = initialMarkState(pts, 2, 3)
    s = stepDown(pts, s, 3)
    expect(totalOf(pts, s, 3)).toBe(1)
    s = stepUp(pts, stepUp(pts, s, 3), 3)
    expect(totalOf(pts, s, 3)).toBe(3)
  })
  it("disables the stepper when the maximum is unknown", () => {
    const s = initialMarkState(Q4, 4, null)
    expect(canStep(Q4, s, null)).toEqual({ down: false, up: false })
    expect(stepUp(Q4, s, null)).toBe(s)
    expect(stepDown(Q4, s, null)).toBe(s)
    const r = initialMarkState([], 2, null)
    expect(canStep([], r, null)).toEqual({ down: false, up: false })
    expect(stepUp([], r, null)).toBe(r)
  })
  it("adds the next eligible point and removes the last ticked", () => {
    let s = initialMarkState(Q4, 4, 5)
    s = stepUp(Q4, s, 5)
    expect(s.ticked.at(-1)).toBe("p6")
    expect(totalOf(Q4, s, 5)).toBe(5)
    expect(canStep(Q4, s, 5)).toEqual({ down: true, up: false })
    s = stepDown(Q4, s, 5)
    s = stepDown(Q4, s, 5)
    expect(totalOf(Q4, s, 5)).toBe(3)
  })
  it("steps a raw number when there are no points", () => {
    let s = initialMarkState([], 1, 3)
    expect(totalOf([], s, 3)).toBe(1)
    s = stepUp([], s, 3)
    s = stepUp([], s, 3)
    s = stepUp([], s, 3)
    expect(totalOf([], s, 3)).toBe(3)
    expect(canStep([], s, 3)).toEqual({ down: true, up: false })
    s = stepDown([], stepDown([], stepDown([], stepDown([], s, 3), 3), 3), 3)
    expect(totalOf([], s, 3)).toBe(0)
    expect(canStep([], s, 3)).toEqual({ down: false, up: true })
  })
})

describe("copy", () => {
  it("states the change against Lemely", () => {
    expect(deltaLine(4, 4)).toBe("as marked by Lemely")
    expect(deltaLine(5, 4)).toBe("+1 from Lemely")
    expect(deltaLine(2, 4)).toBe("−2 from Lemely")
    expect(primaryActionLabel(4, 5, 4)).toBe("Accept 4/5")
    expect(primaryActionLabel(3, 5, 4)).toBe("Save 3/5")
    expect(deltaLine(3, null)).toBe("Lemely gave no mark")
    expect(primaryActionLabel(4, null, 4)).toBe("Accept 4")
    expect(primaryActionLabel(4, null, null)).toBe("Save 4")
    expect(primaryActionLabel(3, null, 4)).toBe("Save 3")
    expect(primaryActionLabel(0, 5, null)).toBe("Save 0/5")
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
    const s = initialMarkState(Q4, 4, 5)
    expect(resolveBody({ points: Q4, state: s, max: 5, lemely: 4, note: " ok ", canAdjust: true })).toEqual({ note: "ok" })
  })
  it("overrides with a tick-derived breakdown and a student note when changed", () => {
    const s = stepDown(Q4, initialMarkState(Q4, 4, 5), 5)
    expect(resolveBody({ points: Q4, state: s, max: 5, lemely: 4, note: "", canAdjust: true })).toEqual({
      overrideMarks: 3,
      breakdown: { methodMarks: 2, accuracyMarks: 0, otherMarks: 1, notes: null },
    })
    expect(breakdownOf(Q4, s)).toEqual({ methodMarks: 2, accuracyMarks: 0, otherMarks: 1, notes: null })
  })
  it("never overrides when the item cannot be adjusted (I16)", () => {
    const s = stepDown(Q4, initialMarkState(Q4, 4, 5), 5)
    expect(resolveBody({ points: Q4, state: s, max: 5, lemely: 4, note: "", canAdjust: false })).toEqual({})
  })
  it("sends no breakdown for a raw-number change", () => {
    const s = stepUp([], initialMarkState([], 1, 3), 3)
    expect(resolveBody({ points: [], state: s, max: 3, lemely: 1, note: "", canAdjust: true })).toEqual({ overrideMarks: 2 })
  })
  it("sends the note alongside an override", () => {
    const s = stepDown(Q4, initialMarkState(Q4, 4, 5), 5)
    expect(resolveBody({ points: Q4, state: s, max: 5, lemely: 4, note: "  Check units ", canAdjust: true })).toEqual({
      overrideMarks: 3,
      breakdown: { methodMarks: 2, accuracyMarks: 0, otherMarks: 1, notes: null },
      note: "Check units",
    })
  })
  it("sends the override when Lemely gave no mark, and labels it Save", () => {
    const s = stepUp([], initialMarkState([], null, 3), 3)
    expect(resolveBody({ points: [], state: s, max: 3, lemely: null, note: "", canAdjust: true })).toEqual({ overrideMarks: 1 })
    const t = initialMarkState(Q4, null, 5)
    expect(resolveBody({ points: Q4, state: t, max: 5, lemely: null, note: "", canAdjust: true }).overrideMarks).toBe(4)
    expect(primaryActionLabel(1, 3, null)).toBe("Save 1/3")
  })
  it("sends a clamped override when Lemely's mark is above the maximum", () => {
    const body = resolveBody({ points: [], state: initialMarkState([], 9, 3), max: 3, lemely: 9, note: "", canAdjust: true })
    expect(body.overrideMarks).toBe(3)
  })
})

describe("breakdownOf", () => {
  it("buckets M and C as method, A as accuracy, and everything else as other", () => {
    const pts = markPointsFrom([
      wire({ markPointId: "m", markType: "M", ordinal: 0 }),
      wire({ markPointId: "c", markType: "C", tariff: 2, ordinal: 1 }),
      wire({ markPointId: "a", markType: "A", ordinal: 2 }),
      wire({ markPointId: "sc", markType: "SC", ordinal: 3 }),
      wire({ markPointId: "b", markType: "B", ordinal: 4 }),
      wire({ markPointId: "p9", markType: null, ordinal: 5 }),
    ])
    expect(pts.map((p) => p.code)).toEqual(["M1", "C2", "A1", "SC1", "B1", "p9"])
    const all: MarkState = { ticked: pts.map((p) => p.markPointId), touched: true, raw: 0 }
    expect(breakdownOf(pts, all)).toEqual({ methodMarks: 3, accuracyMarks: 1, otherMarks: 3, notes: null })
    expect(breakdownOf(pts, { ...all, ticked: ["sc"] })).toEqual({ methodMarks: 0, accuracyMarks: 0, otherMarks: 1, notes: null })
    expect(breakdownOf(pts, { ...all, ticked: [] })).toEqual({ methodMarks: 0, accuracyMarks: 0, otherMarks: 0, notes: null })
    expect(breakdownOf([], all)).toBeUndefined()
  })
})

describe("fix round 1", () => {
  it("never commits an override the teacher did not make when ticks cannot reach Lemely's total", () => {
    const one = markPointsFrom([wire({ markPointId: "p1", tariff: 3, ordinal: 0 })])
    const s = initialMarkState(one, 1, 5)
    expect(totalOf(one, s, 5)).toBe(1)
    expect(resolveBody({ points: one, state: s, max: 5, lemely: 1, note: "", canAdjust: true })).toEqual({})
  })
  it("has no save when there is no way to enter a mark", () => {
    const s = initialMarkState([], null, null)
    expect(canSave([], s, null, null)).toBe(false)
    expect(resolveBody({ points: [], state: s, max: null, lemely: null, note: "", canAdjust: true }).overrideMarks).toBeUndefined()
    expect(canSave([], s, 3, null)).toBe(true)
    expect(canSave([], s, null, 2)).toBe(true)
    expect(canSave(Q4, initialMarkState(Q4, null, null), null, null)).toBe(true)
  })
  it("explains an above-max clamp", () => {
    expect(clampNote(9, 3)).toBe("Lemely gave 9, above the maximum of 3, so it is shown as 3")
    expect(clampNote(3, 3)).toBeNull()
    expect(clampNote(null, 3)).toBeNull()
    expect(clampNote(9, null)).toBeNull()
  })
})
