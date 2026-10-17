import { describe, expect, it } from "vitest"
import { gradeRank, widestVocabulary, widestVocabularyFor } from "@/lib/grades"

// The real served pair for 0580, verified live: Core and Extended are both
// partial views of one ladder, and neither is a superset of the other —
// Core has F/G that Extended lacks, Extended has A*, A and B that Core lacks.
const IGCSE_0580_CORE = ["C", "D", "E", "F", "G", "U"]
const IGCSE_0580_EXTENDED = ["A*", "A", "B", "C", "D", "E", "U"]

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
  it("unions all served grades for a subject in ladder order, not just the longest tier", () => {
    // The regression this covers: picking the single longest served array
    // (length 7, Extended) would silently drop F and G, which Core-tier
    // students genuinely receive. Only a union recovers the full ladder.
    const vocabularies = [
      { subjectCode: "0580", grades: IGCSE_0580_CORE },
      { subjectCode: "0580", grades: IGCSE_0580_EXTENDED },
    ]
    const union = widestVocabularyFor(vocabularies, "0580")
    expect(union).toEqual(["A*", "A", "B", "C", "D", "E", "F", "G", "U"])
    for (const grade of ["F", "G", "A*", "A", "B"]) {
      expect(union).toContain(grade)
    }
  })

  it("ranks a Core F between E and G, not after U, once the tiers are unioned", () => {
    const vocabularies = [
      { subjectCode: "0580", grades: IGCSE_0580_CORE },
      { subjectCode: "0580", grades: IGCSE_0580_EXTENDED },
    ]
    const union = widestVocabularyFor(vocabularies, "0580")
    expect(gradeRank("F", union)).toBeGreaterThan(gradeRank("E", union))
    expect(gradeRank("F", union)).toBeLessThan(gradeRank("G", union))
    expect(gradeRank("F", union)).toBeLessThan(gradeRank("U", union))
  })

  it("is order-independent: unioning Extended before Core gives the same ladder", () => {
    const vocabularies = [
      { subjectCode: "0580", grades: IGCSE_0580_EXTENDED },
      { subjectCode: "0580", grades: IGCSE_0580_CORE },
    ]
    expect(widestVocabularyFor(vocabularies, "0580")).toEqual([
      "A*", "A", "B", "C", "D", "E", "F", "G", "U",
    ])
  })

  it("returns an empty list when the subject has no served vocabulary", () => {
    expect(widestVocabularyFor([{ subjectCode: "0606", grades: ["A*", "A"] }], "0580")).toEqual([])
  })
})

describe("widestVocabulary", () => {
  it("unions across subjects too, not just the longest one served", () => {
    // Guards the same defect for AtRiskList's cross-subject fallback: today
    // 0625 happens to serve the full 9-grade ladder, but that must not be
    // load-bearing — a union is correct even if no single subject ever
    // covers every grade.
    const vocabularies = [
      { subjectCode: "0580", grades: IGCSE_0580_CORE },
      { subjectCode: "0580", grades: IGCSE_0580_EXTENDED },
    ]
    expect(widestVocabulary(vocabularies)).toEqual(["A*", "A", "B", "C", "D", "E", "F", "G", "U"])
  })
})
