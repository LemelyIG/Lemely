import { describe, expect, it } from "vitest"
import { filterQuestions, isFlagged, markState } from "@/lib/questionFilter"
import { confidenceTierFor } from "@/lib/markingConfidence"
import type { QuestionResult } from "@/lib/types"

function q(overrides: Partial<QuestionResult>): QuestionResult {
  return {
    questionId: "1",
    awardedMarks: 0,
    maxMarks: 4,
    markerSource: "deterministic",
    ...overrides,
  }
}

describe("markState", () => {
  it("full marks is correct", () => {
    expect(markState(q({ awardedMarks: 4, maxMarks: 4 }))).toBe("correct")
  })

  it("zero marks is wrong", () => {
    expect(markState(q({ awardedMarks: 0, maxMarks: 4 }))).toBe("wrong")
  })

  it("anything between is partial", () => {
    expect(markState(q({ awardedMarks: 2, maxMarks: 4 }))).toBe("partial")
  })

  it("maxMarks 0 with awarded > 0 is correct", () => {
    expect(markState(q({ awardedMarks: 1, maxMarks: 0 }))).toBe("correct")
  })

  it("maxMarks 0 with awarded 0 is wrong", () => {
    expect(markState(q({ awardedMarks: 0, maxMarks: 0 }))).toBe("wrong")
  })
})

describe("isFlagged", () => {
  it("true when reviewReason is set", () => {
    expect(isFlagged(q({ reviewReason: "Handwriting unclear", confidence: 0.99 }))).toBe(true)
  })

  it("true on the lowest tier of the ConfidenceTier union", () => {
    // `confidenceTierFor` in lib/markingConfidence.ts is the source of truth
    // for which tier is lowest: "needs-review" (the union is "confident" |
    // "uncertain" | "needs-review", and only a set reviewReason ever
    // produces it). Pinned here directly so a change to that ordering shows
    // up as a failure in the function this test names, not a silent drift.
    const flagged = q({ reviewReason: "Handwriting unclear" })
    expect(confidenceTierFor(flagged)).toBe("needs-review")
    expect(isFlagged(flagged)).toBe(true)
  })

  it("false on a confident, unflagged question", () => {
    expect(isFlagged(q({ confidence: 0.99 }))).toBe(false)
  })

  it("false on the middle tier ('uncertain'), below the review floor but not flagged", () => {
    expect(confidenceTierFor(q({ confidence: 0.5 }))).toBe("uncertain")
    expect(isFlagged(q({ confidence: 0.5 }))).toBe(false)
  })
})

describe("filterQuestions", () => {
  const questions: QuestionResult[] = [
    q({ questionId: "1", awardedMarks: 4, maxMarks: 4, confidence: 0.99 }), // correct, not flagged
    q({ questionId: "2", awardedMarks: 0, maxMarks: 4, confidence: 0.99 }), // wrong, not flagged
    q({ questionId: "3", awardedMarks: 2, maxMarks: 4, confidence: 0.5 }), // partial, uncertain but not flagged
    q({ questionId: "4", awardedMarks: 4, maxMarks: 4, reviewReason: "Integrity check" }), // correct, flagged (reviewReason)
  ]

  it("all returns every question", () => {
    expect(filterQuestions(questions, "all").map((r) => r.questionId)).toEqual([
      "1",
      "2",
      "3",
      "4",
    ])
  })

  it("lost returns everything short of full marks", () => {
    expect(filterQuestions(questions, "lost").map((r) => r.questionId)).toEqual(["2", "3"])
  })

  it("flagged returns everything isFlagged reports true for", () => {
    expect(filterQuestions(questions, "flagged").map((r) => r.questionId)).toEqual(["4"])
  })
})
