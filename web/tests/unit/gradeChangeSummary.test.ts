import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"
import {
  GRADE_CHANGE_PARTS,
  GRADE_CHANGE_TITLE,
  gradeChangeAriaLabel,
  gradeChangeCaption,
  gradeChangeHidden,
  gradeChangeTableRows,
  layoutGradeChange,
} from "@/lib/tutoring/gradeChange"
import { stripComments } from "./support/jsxSource"

/*
 * C-18 (SPEC §d): the higher / same / lower figure. The title and the three
 * part labels are read out of the SPEC's own catalogue row, so the component
 * cannot drift from it (and the test is not comparing a literal with itself).
 */

const SPEC = readFileSync(
  join(import.meta.dirname, "..", "..", "..", "docs", "tutoring", "SPEC.md"),
  "utf8",
)
const ROW = SPEC.split("\n").find((line) => line.startsWith("| C-18 |")) ?? ""

describe("SPEC row C-18 is found", () => {
  it("is one table row", () => {
    expect(ROW.length).toBeGreaterThan(0)
  })
})

describe("fixed copy", () => {
  it("title equals the fixed title in the SPEC row", () => {
    const title = /Title fixed: "([^"]+)"/.exec(ROW)?.[1]
    expect(title).toBe("Change in grade while with this tutor")
    expect(GRADE_CHANGE_TITLE).toBe(title)
  })

  it("parts read Lower grade, Same grade, Higher grade, in that order, as in the SPEC", () => {
    const quoted = /"(Lower grade · Same grade · Higher grade)"/.exec(ROW)?.[1]
    expect(quoted).toBeDefined()
    expect(GRADE_CHANGE_PARTS.map((p) => p.label).join(" · ")).toBe(quoted)
    expect(GRADE_CHANGE_PARTS.map((p) => p.key)).toEqual(["lower", "same", "higher"])
  })

  it("never uses the words the copy rule bans", () => {
    const copy = [GRADE_CHANGE_TITLE, ...GRADE_CHANGE_PARTS.map((p) => p.label)].join(" ")
    expect(copy).not.toMatch(/\b(?:improvements?|verified)\b/i)
  })
})

describe("layoutGradeChange", () => {
  it("lists all three parts in order with their counts and shares of n", () => {
    const layout = layoutGradeChange({ lower: 1, same: 3, higher: 4 })
    expect(layout.n).toBe(8)
    expect(layout.parts.map((p) => [p.key, p.count])).toEqual([
      ["lower", 1],
      ["same", 3],
      ["higher", 4],
    ])
    expect(layout.parts.map((p) => p.widthPct)).toEqual([12.5, 37.5, 50])
    expect(layout.parts.map((p) => p.startPct)).toEqual([0, 12.5, 50])
  })

  it("keeps an empty part in the list with 0 and no width", () => {
    const layout = layoutGradeChange({ lower: 0, same: 2, higher: 3 })
    expect(layout.parts).toHaveLength(3)
    expect(layout.parts[0]).toMatchObject({ key: "lower", count: 0, widthPct: 0 })
  })

  it("an all-zero change has n 0 and no widths", () => {
    const layout = layoutGradeChange({ lower: 0, same: 0, higher: 0 })
    expect(layout.n).toBe(0)
    expect(layout.parts.every((p) => p.widthPct === 0)).toBe(true)
  })

  it("treats a null count as 0 rather than inventing one", () => {
    const layout = layoutGradeChange({ lower: null, same: 4, higher: null })
    expect(layout.n).toBe(4)
    expect(layout.parts.map((p) => p.count)).toEqual([0, 4, 0])
  })
})

describe("text alternative", () => {
  const layout = layoutGradeChange({ lower: 1, same: 3, higher: 4 })

  it("aria-label is a full sentence naming each part and n", () => {
    const label = gradeChangeAriaLabel(layout)
    expect(label).toBe(
      "Change in grade while with this tutor, 8 students: lower grade 1, same grade 3, higher grade 4.",
    )
  })

  it("table rows are the three parts with counts as text", () => {
    expect(gradeChangeTableRows(layout)).toEqual([
      ["Lower grade", "1"],
      ["Same grade", "3"],
      ["Higher grade", "4"],
    ])
  })

  it("caption states n, singular for one student", () => {
    expect(gradeChangeCaption(8)).toContain("8 students")
    expect(gradeChangeCaption(1)).toContain("1 student")
    expect(gradeChangeCaption(1)).not.toContain("1 students")
  })
})

describe("gradeChangeHidden", () => {
  const sufficient = (nPaired: number | null, k = 5, counts = { lower: 0, same: 0, higher: 0 }) => ({
    state: "sufficient" as const,
    k,
    nPaired,
    ...counts,
  })

  it("is hidden when the server says insufficient", () => {
    expect(
      gradeChangeHidden({ state: "insufficient", k: 5, nPaired: null, lower: null, same: null, higher: null }),
    ).toBe(true)
  })

  it("is hidden when the server says sufficient but fewer than k students are paired", () => {
    expect(gradeChangeHidden(sufficient(4, 5, { lower: 1, same: 1, higher: 2 }))).toBe(true)
    expect(gradeChangeHidden(sufficient(0))).toBe(true)
  })

  it("is shown at exactly k and above", () => {
    expect(gradeChangeHidden(sufficient(5, 5, { lower: 1, same: 1, higher: 3 }))).toBe(false)
  })

  it("falls back to the three counts when nPaired is missing", () => {
    expect(gradeChangeHidden(sufficient(null, 5, { lower: 1, same: 1, higher: 1 }))).toBe(true)
    expect(gradeChangeHidden(sufficient(null, 5, { lower: 2, same: 2, higher: 1 }))).toBe(false)
  })
})

describe("hidden state never shows counts", () => {
  it("the component decides before it lays anything out, and the hidden branch reads only k", () => {
    const source = stripComments(
      readFileSync(
        join(import.meta.dirname, "..", "..", "src", "components", "ui", "grade-change-summary.tsx"),
        "utf8",
      ),
    )
    const guard = source.indexOf("if (gradeChangeHidden(")
    const layoutAt = source.indexOf("const layout = layoutGradeChange(change)")
    expect(guard).toBeGreaterThan(-1)
    expect(layoutAt).toBeGreaterThan(guard)
    const hiddenBranch = source.slice(guard, layoutAt)
    expect(hiddenBranch).toContain("insufficientResultsBody(change.k)")
    expect(hiddenBranch).not.toMatch(/nPaired|\.lower|\.same|\.higher|\.count|layout|parts/)
  })
})

describe("component source (C-18), no colour-only encoding", () => {
  const source = stripComments(
    readFileSync(
      join(import.meta.dirname, "..", "..", "src", "components", "ui", "grade-change-summary.tsx"),
      "utf8",
    ),
  )

  it("ties each segment of the bar to its icon, label and count with a swatch of the segment's own fill", () => {
    expect(source).toContain("partSwatch")
    // Every swatch class is the segment's fill under a background name.
    expect(source).toMatch(/lower: "bg-rule-strong"/)
    expect(source).toMatch(/same: "bg-ink-faint"/)
    expect(source).toMatch(/higher: "bg-ink-muted"/)
    expect(source).toMatch(/lower: "fill-rule-strong"/)
    expect(source).toMatch(/same: "fill-ink-faint"/)
    expect(source).toMatch(/higher: "fill-ink-muted"/)
  })

  it("keeps the icon, the word and the count in the same item as the swatch", () => {
    const item = source.slice(source.indexOf("layout.parts.map((part) => {"), source.indexOf("<figcaption"))
    expect(item).toContain("partSwatch[part.key]")
    expect(item).toContain("<PartIcon")
    expect(item).toContain("part.label")
    expect(item).toContain("part.count")
  })
})

describe("component source (C-18)", () => {
  const readRaw = () => readFileSync(
    join(import.meta.dirname, "..", "..", "src", "components", "ui", "grade-change-summary.tsx"),
    "utf8",
  )
  // Comments are blanked: the file's header prose quotes the very strings checked here.
  const read = () => stripComments(readRaw())

  it("takes its title from the constant and accepts no title prop", () => {
    expect(read()).toContain("GRADE_CHANGE_TITLE")
    // Comments are blanked first: the header prose says "fixed title:".
    expect(stripComments(read())).not.toMatch(/\btitle\??\s*:/)
  })

  it("pairs each part with an icon and offers the table alternative", () => {
    expect(read()).toContain("ArrowDown")
    expect(read()).toContain("Equals")
    expect(read()).toContain("ArrowUp")
    expect(read()).toContain("<caption")
    expect(read()).toContain("Show as table")
  })

  it("uses neutral tokens, not the grade-band colours that would grade the tutor", () => {
    expect(read()).not.toMatch(/grade-(?:top|mid|borderline|fail)/)
    expect(read()).not.toMatch(/\b(?:bg|text)-(?:ok|err)\b/)
  })
})
