import { describe, expect, it } from "vitest"
import {
  MIN_INSIDE_LABEL_PCT,
  MIN_OUTSIDE_LABEL_GAP_PCT,
  INSUFFICIENT_RESULTS_HEADING,
  distributionAriaLabel,
  distributionCaption,
  distributionHidden,
  distributionTableRows,
  insufficientResultsBody,
  layoutOrdinal,
  spreadLabelPositions,
} from "@/lib/tutoring/ordinalLayout"
import { readFileSync } from "node:fs"
import { join } from "node:path"
import { stripComments } from "./support/jsxSource"

/*
 * C-17 (SPEC §d): the ordered grade bar. The pure layout is tested here; the
 * runner has no DOM (D3.20), so the component is covered through its logic and
 * a structural read of its source.
 *
 * The ladder is whatever `OutcomesDTO.ladder` says (SPEC §i.1 row 19: A*..E, U).
 * It is written out in this file only because a test needs concrete input; the
 * component never declares one (noHardcodedReferenceData.test.ts guards src/).
 */

const LADDER = ["A*", "A", "B", "C", "D", "E", "U"]

const SPEC = readFileSync(
  join(import.meta.dirname, "..", "..", "..", "docs", "tutoring", "SPEC.md"),
  "utf8",
)

describe("layoutOrdinal", () => {
  it("lists every rung of the ladder in ladder order, zero rungs included", () => {
    const layout = layoutOrdinal(LADDER, [
      { grade: "B", count: 5 },
      { grade: "A", count: 2 },
      { grade: "E", count: 1 },
    ])
    expect(layout.rungs.map((r) => r.grade)).toEqual(LADDER)
    expect(layout.rungs.map((r) => r.count)).toEqual([0, 2, 5, 0, 0, 1, 0])
  })

  it("draws a segment only for a non-zero rung, in ladder order", () => {
    const layout = layoutOrdinal(LADDER, [
      { grade: "B", count: 5 },
      { grade: "A", count: 2 },
      { grade: "E", count: 1 },
    ])
    expect(layout.segments.map((s) => s.grade)).toEqual(["A", "B", "E"])
    expect(layout.n).toBe(8)
  })

  it("segment widths are shares of n and add up to the whole bar", () => {
    const layout = layoutOrdinal(LADDER, [
      { grade: "A", count: 1 },
      { grade: "B", count: 3 },
    ])
    expect(layout.segments.map((s) => s.widthPct)).toEqual([25, 75])
    expect(layout.segments.map((s) => s.startPct)).toEqual([0, 25])
    const total = layout.segments.reduce((sum, s) => sum + s.widthPct, 0)
    expect(total).toBeCloseTo(100, 6)
  })

  it("moves the label outside a segment narrower than the inside threshold", () => {
    // 1 of 41 is about 2.4%; 40 of 41 is about 97.6%.
    const layout = layoutOrdinal(LADDER, [
      { grade: "A*", count: 1 },
      { grade: "B", count: 40 },
    ])
    const [narrow, wide] = layout.segments
    expect(narrow.widthPct).toBeLessThan(MIN_INSIDE_LABEL_PCT)
    expect(narrow.labelPlacement).toBe("outside")
    expect(wide.labelPlacement).toBe("inside")
  })

  it("keeps outside labels apart and inside the bar even when narrow segments are adjacent", () => {
    // Four 1-student segments beside a big one: their centres are about 2% apart.
    const layout = layoutOrdinal(LADDER, [
      { grade: "A*", count: 1 },
      { grade: "A", count: 1 },
      { grade: "B", count: 1 },
      { grade: "C", count: 1 },
      { grade: "D", count: 60 },
    ])
    const outside = layout.segments.filter((s) => s.labelPlacement === "outside")
    expect(outside.map((s) => s.grade)).toEqual(["A*", "A", "B", "C"])
    const xs = outside.map((s) => s.labelPct)
    for (let i = 1; i < xs.length; i++) {
      expect(xs[i] - xs[i - 1]).toBeGreaterThanOrEqual(MIN_OUTSIDE_LABEL_GAP_PCT - 1e-9)
    }
    for (const x of xs) {
      expect(x).toBeGreaterThanOrEqual(0)
      expect(x).toBeLessThanOrEqual(100)
    }
  })

  it("keeps a grade the ladder does not list, after the ladder, rather than dropping a student", () => {
    const layout = layoutOrdinal(LADDER, [
      { grade: "B", count: 2 },
      { grade: "F", count: 1 },
    ])
    expect(layout.rungs.map((r) => r.grade)).toEqual([...LADDER, "F"])
    expect(layout.n).toBe(3)
  })

  it("adds up buckets that repeat a grade", () => {
    const layout = layoutOrdinal(LADDER, [
      { grade: "B", count: 2 },
      { grade: "B", count: 3 },
    ])
    expect(layout.rungs.find((r) => r.grade === "B")?.count).toBe(5)
    expect(layout.n).toBe(5)
  })

  it("an empty distribution still lists every rung at 0 and draws nothing", () => {
    const layout = layoutOrdinal(LADDER, [])
    expect(layout.n).toBe(0)
    expect(layout.segments).toEqual([])
    expect(layout.rungs.map((r) => r.count)).toEqual([0, 0, 0, 0, 0, 0, 0])
  })
})

describe("spreadLabelPositions", () => {
  it("returns centres untouched when they already clear the gap", () => {
    expect(spreadLabelPositions([10, 40, 80], 9)).toEqual([10, 40, 80])
  })

  it("pushes crowded labels apart and keeps them in range, in order", () => {
    const out = spreadLabelPositions([1, 2, 3, 99, 100], 9)
    for (let i = 1; i < out.length; i++) expect(out[i] - out[i - 1]).toBeGreaterThanOrEqual(9 - 1e-9)
    expect(Math.min(...out)).toBeGreaterThanOrEqual(0)
    expect(Math.max(...out)).toBeLessThanOrEqual(100)
  })

  it("returns an empty list for no labels", () => {
    expect(spreadLabelPositions([], 9)).toEqual([])
  })
})

describe("text alternative", () => {
  const layout = layoutOrdinal(LADDER, [
    { grade: "A", count: 2 },
    { grade: "B", count: 5 },
  ])

  it("aria-label is a full sentence that names every rung, zero rungs with 0", () => {
    const label = distributionAriaLabel("Mathematics", layout)
    expect(label.startsWith("Mathematics: grades of 7 students.")).toBe(true)
    expect(label.endsWith(".")).toBe(true)
    // Every rung is spoken, the empty ones as 0, in ladder order.
    expect(label).toContain("A* 0, A 2, B 5, C 0, D 0, E 0, U 0")
  })

  it("table rows are the rungs in ladder order with their counts as text", () => {
    expect(distributionTableRows(layout)).toEqual([
      ["A*", "0"],
      ["A", "2"],
      ["B", "5"],
      ["C", "0"],
      ["D", "0"],
      ["E", "0"],
      ["U", "0"],
    ])
  })

  it("caption states n, in the singular for one student", () => {
    expect(distributionCaption(12, 0)).toContain("12 students")
    expect(distributionCaption(1, null)).toContain("1 student")
    expect(distributionCaption(1, null)).not.toContain("1 students")
  })

  it("caption says how many more have no grade, only when there are some", () => {
    expect(distributionCaption(8, 2)).toContain("2")
    expect(distributionCaption(8, 0)).not.toMatch(/no grade/i)
    expect(distributionCaption(8, null)).not.toMatch(/no grade/i)
  })
})

describe("insufficient state copy", () => {
  it("matches SPEC S-34 and takes k from the figure, not from a literal", () => {
    expect(SPEC).toContain(
      `"Results are hidden for now. We show them only when at least 5 students have a marked paper from their time with this tutor, and only when no one's grade could be worked out from them."`,
    )
    expect(`${INSUFFICIENT_RESULTS_HEADING}. ${insufficientResultsBody(5)}`).toBe(
      "Results are hidden for now. We show them only when at least 5 students have a marked paper from their time with this tutor, and only when no one's grade could be worked out from them.",
    )
    expect(insufficientResultsBody(7)).toContain("at least 7 students")
  })
})

describe("distributionHidden", () => {
  const sufficient = (nGraded: number | null, k = 5, buckets: { grade: string; count: number }[] = []) => ({
    state: "sufficient" as const,
    k,
    nGraded,
    buckets,
  })

  it("is hidden whenever the server says insufficient", () => {
    expect(distributionHidden({ state: "insufficient", k: 5, nGraded: null, buckets: [] })).toBe(true)
  })

  it("is hidden when the server says sufficient but fewer than k students are graded", () => {
    expect(distributionHidden(sufficient(4))).toBe(true)
    expect(distributionHidden(sufficient(0))).toBe(true)
  })

  it("is shown at exactly k and above", () => {
    expect(distributionHidden(sufficient(5))).toBe(false)
    expect(distributionHidden(sufficient(40))).toBe(false)
  })

  it("falls back to the buckets when nGraded is missing, and hides when they fall short of k", () => {
    expect(distributionHidden(sufficient(null, 5, [{ grade: "A", count: 2 }]))).toBe(true)
    expect(distributionHidden(sufficient(null, 5, [{ grade: "A", count: 3 }, { grade: "B", count: 2 }]))).toBe(false)
    expect(distributionHidden(sufficient(null))).toBe(true)
  })
})

describe("hidden state never shows counts", () => {
  it("its sentence carries k and no other number", () => {
    for (const k of [1, 5, 12]) {
      const text = `${INSUFFICIENT_RESULTS_HEADING}. ${insufficientResultsBody(k)}`
      expect(text.replace(String(k), "")).not.toMatch(/\d/)
    }
  })

  it("the component decides before it lays anything out, and the hidden branch reads only k", () => {
    const source = stripComments(
      readFileSync(
        join(import.meta.dirname, "..", "..", "src", "components", "ui", "ordinal-distribution.tsx"),
        "utf8",
      ),
    )
    const guard = source.indexOf("if (distributionHidden(")
    const layoutAt = source.indexOf("const layout = layoutOrdinal(ladder")
    expect(guard).toBeGreaterThan(-1)
    expect(layoutAt).toBeGreaterThan(guard)
    const hiddenBranch = source.slice(guard, layoutAt)
    expect(hiddenBranch).toContain("insufficientResultsBody(distribution.k)")
    expect(hiddenBranch).not.toMatch(/nGraded|nWithoutGrade|buckets|\.count|layout|rungs/)
  })
})

describe("component source (C-17)", () => {
  const readRaw = () => readFileSync(
    join(import.meta.dirname, "..", "..", "src", "components", "ui", "ordinal-distribution.tsx"),
    "utf8",
  )
  // Comments are blanked: the file's header prose quotes the very strings checked here.
  const read = () => stripComments(readRaw())

  it("is SVG with a real table alternative behind a toggle", () => {
    expect(read()).toContain("<svg")
    // The kit's `Table` renders the real <table>; the caption goes inside it.
    expect(read()).toContain("<caption")
    expect(read()).toContain("<Table")
    expect(read()).toContain("aria-pressed")
    expect(read()).toContain("Show as table")
  })

  it("colours each segment through gradeBand and never declares a ladder", () => {
    expect(read()).toContain("gradeBand")
    expect(read()).not.toMatch(/\[\s*"A\*"\s*,/)
  })
})
