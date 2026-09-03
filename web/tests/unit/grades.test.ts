import { describe, expect, it } from "vitest"
import { gradeRank, widestVocabularyFor } from "@/lib/grades"

const IGCSE_EXTENDED = ["A*", "A", "B", "C", "D", "E", "F", "G", "U"]
const A_LEVEL = ["A*", "A", "B", "C", "D", "E", "U"]

describe("gradeRank", () => {
  it("ranks by position in the given vocabulary, best first", () => {
    expect(gradeRank("A*", IGCSE_EXTENDED)).toBe(0)
    expect(gradeRank("U", IGCSE_EXTENDED)).toBe(8)
  })

  it("sorts an unrecognised grade last, never first", () => {
    // The defect this function exists for. Four screens used
    // `GRADE_ORDER.indexOf(grade)` over a vocabulary without F or G, so a
    // Core-tier F scored -1 and sorted ahead of an A*. 234 of 350 boundary
    // records award F or G, so this was reachable, not theoretical.
    expect(gradeRank("F", A_LEVEL)).toBeGreaterThan(gradeRank("U", A_LEVEL))
  })

  it("sorts a null or missing grade last", () => {
    expect(gradeRank(null, A_LEVEL)).toBeGreaterThan(gradeRank("U", A_LEVEL))
    expect(gradeRank(undefined, A_LEVEL)).toBeGreaterThan(gradeRank("U", A_LEVEL))
  })

  it("orders a real mixed list correctly when sorted ascending", () => {
    const sorted = ["U", "F", "A*", "C"].sort((a, b) =>
      gradeRank(a, IGCSE_EXTENDED) - gradeRank(b, IGCSE_EXTENDED),
    )
    expect(sorted).toEqual(["A*", "C", "F", "U"])
  })

  it("returns the same rank for an empty vocabulary regardless of grade", () => {
    // While `/api/reference` is loading there is no vocabulary. Every grade
    // ranking equal keeps a table's order stable rather than scrambling it.
    expect(gradeRank("A*", [])).toBe(gradeRank("U", []))
  })
})

describe("widestVocabularyFor", () => {
  it("picks the longest served vocabulary for a subject", () => {
    const vocabularies = [
      { subjectCode: "0580", grades: ["A*", "A", "B", "C", "D", "E", "U"] },
      { subjectCode: "0625", grades: ["A*", "A", "B", "C", "D", "E", "F", "G", "U"] },
    ]
    expect(widestVocabularyFor(vocabularies, "0625")).toEqual([
      "A*", "A", "B", "C", "D", "E", "F", "G", "U",
    ])
  })

  it("returns an empty list when the subject has no served vocabulary", () => {
    expect(widestVocabularyFor([{ subjectCode: "0606", grades: ["A*", "A"] }], "0580")).toEqual([])
  })
})
