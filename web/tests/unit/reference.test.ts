import { describe, expect, it } from "vitest"
import {
  CONFIDENCE_TOPICS_SHOWN,
  confidenceTopicsFor,
  subjectFor,
  subjectNameFor,
} from "@/lib/reference"
import type { CatalogueSubject, ReferenceData } from "@/lib/referenceTypes"

function subject(code: string, name: string, topics: string[] = []): CatalogueSubject {
  return { code, name, board: "caie", qualificationLevel: "igcse", papers: [], topics }
}

const REFERENCE: ReferenceData = {
  subjects: [
    subject("0580", "Mathematics"),
    subject("0625", "Physics", [
      "1 Motion, forces and energy",
      "2 Thermal physics",
      "3 Waves",
      "4 Electricity and magnetism",
    ]),
  ],
  targetGradeVocabularies: [],
  qualificationLevels: [],
  sessionMonths: [],
  difficultyBands: [],
}

describe("subjectNameFor", () => {
  it("resolves a known code to its catalogue name", () => {
    expect(subjectNameFor(REFERENCE, "0625")).toBe("Physics")
  })

  it("falls back to the raw code for an unknown subject", () => {
    // The exact expression the seven lookup screens used before this existed
    // (`SUPPORTED_SUBJECTS.find(...)?.name ?? subjectCode`). Keeping it means a
    // subject added to the catalogue before a screen knows about it degrades to
    // showing the code, never to showing nothing.
    expect(subjectNameFor(REFERENCE, "9709")).toBe("9709")
  })

  it("falls back to the raw code while the query is still loading", () => {
    // `undefined` is what react-query hands a component on first render. A
    // screen must render the code, not crash and not flash an empty heading.
    expect(subjectNameFor(undefined, "0625")).toBe("0625")
  })
})

describe("subjectFor", () => {
  it("returns the catalogue entry for a known code", () => {
    expect(subjectFor(REFERENCE, "0580")?.name).toBe("Mathematics")
  })

  it("returns null rather than undefined for an unknown code", () => {
    expect(subjectFor(REFERENCE, "9999")).toBeNull()
  })

  it("returns null while the query is loading", () => {
    expect(subjectFor(undefined, "0625")).toBeNull()
  })
})

describe("confidenceTopicsFor", () => {
  it("shows the first three topics, preserving S-02's existing behaviour", () => {
    // The endpoint returns every top-level topic (0606 has fourteen). How many
    // to ask about is a UI decision, not a curriculum fact, so the slice lives
    // here rather than in the backend.
    expect(confidenceTopicsFor(subjectFor(REFERENCE, "0625"))).toEqual([
      "1 Motion, forces and energy",
      "2 Thermal physics",
      "3 Waves",
    ])
  })

  it("returns an empty list for a subject with no topics", () => {
    expect(confidenceTopicsFor(subjectFor(REFERENCE, "0580"))).toEqual([])
  })

  it("returns an empty list for a missing subject", () => {
    expect(confidenceTopicsFor(null)).toEqual([])
  })

  it("pins the count so a change is a deliberate edit", () => {
    expect(CONFIDENCE_TOPICS_SHOWN).toBe(3)
  })
})
