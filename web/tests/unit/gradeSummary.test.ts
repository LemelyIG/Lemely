import { describe, expect, it } from "vitest"
import { topGradeCount } from "@/lib/gradeSummary"

/*
 * Task 9 (C3d) · `topGradeCount` sums the buckets `gradeBand` (from
 * `components/ui/grade-badge.tsx`) classes as "top" — A*, A and B.
 */

const FIXTURE = [
  { grade: "A*", count: 3 },
  { grade: "A", count: 5 },
  { grade: "B", count: 2 },
  { grade: "U", count: 4 },
] as const

describe("topGradeCount", () => {
  it("sums A*, A and B — the buckets gradeBand classes as 'top'", () => {
    expect(topGradeCount(FIXTURE)).toBe(10)
  })

  it("is 0 when nobody is in the top band", () => {
    expect(topGradeCount([{ grade: "C", count: 6 }, { grade: "U", count: 2 }])).toBe(0)
  })

  it("is 0 on an empty bucket list", () => {
    expect(topGradeCount([])).toBe(0)
  })

  it("ignores mid/borderline/fail buckets even when nonzero alongside a top one", () => {
    expect(
      topGradeCount([
        { grade: "A*", count: 1 },
        { grade: "C", count: 9 },
        { grade: "D", count: 9 },
        { grade: "E", count: 9 },
        { grade: "F", count: 9 },
        { grade: "G", count: 9 },
      ]),
    ).toBe(1)
  })
})
