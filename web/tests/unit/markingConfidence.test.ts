import { describe, expect, it } from "vitest"
import {
  confidenceSummaryOf,
  confidenceTierFor,
  REVIEW_CONFIDENCE_THRESHOLD,
} from "@/lib/markingConfidence"

/*
 * P4.2 · The student's confidence bucketing must agree with the teacher's.
 *
 * The defect these pin: `PaperResult` used a 0.85 threshold it had invented,
 * while the backend and the teacher portal use 0.90. A mark between the two
 * numbers was described differently to the two people looking at the same
 * paper. `tests/test_design_tokens.py` pins the constant against the Python
 * definition; these pin the behaviour that hangs off it.
 */

describe("confidenceTierFor", () => {
  it("uses the backend's 0.90 review floor, not a frontend guess", () => {
    expect(REVIEW_CONFIDENCE_THRESHOLD).toBe(0.9)
    // The whole point: this value used to be called confident.
    expect(confidenceTierFor({ confidence: 0.87 })).toBe("uncertain")
    expect(confidenceTierFor({ confidence: 0.9 })).toBe("confident")
    expect(confidenceTierFor({ confidence: 0.899 })).toBe("uncertain")
  })

  it("lets an explicit review reason win at any confidence", () => {
    // Integrity checks set `reviewReason` without touching the score, so a
    // flagged question can be at 1.0 and still need a human.
    expect(confidenceTierFor({ confidence: 1, reviewReason: "Handwriting unclear" })).toBe(
      "needs-review",
    )
    expect(confidenceTierFor({ confidence: 0.2, reviewReason: "Answer off-scheme" })).toBe(
      "needs-review",
    )
  })

  it("stale-flag defect (S2 review): a settled self-review beats a frozen reviewReason", () => {
    // A resolved `low_confidence` queue row: `pendingTeacher: false` says no
    // teacher review is open for this question *right now*, and that wins
    // outright even though `reviewReason` -- the marker's frozen record of
    // why it was once flagged -- is still sitting there, unrewritten by
    // design. Before this fix there was no `pendingTeacher` signal at all,
    // so a self-reviewed, fully-settled question still read "needs-review"
    // forever.
    expect(
      confidenceTierFor({ reviewReason: "low confidence", pendingTeacher: false }),
    ).toBe("confident")
    // `pendingTeacher: true` (still open) behaves exactly as `reviewReason`
    // alone always has.
    expect(
      confidenceTierFor({ reviewReason: "low confidence", pendingTeacher: true }),
    ).toBe("needs-review")
    // `pendingTeacher` absent (a teacher-console grade, a live
    // `/student/correct` frame -- no queue to ask) must not change today's
    // behaviour for every source that never sends the field.
    expect(confidenceTierFor({ reviewReason: "low confidence" })).toBe("needs-review")
  })

  it("treats a missing score as confident rather than doubtful", () => {
    // The arguable call, made deliberately: MCQ marking is deterministic
    // string comparison and carries no score, so the alternative would flag
    // every question on a 40-question MCQ paper as uncertain.
    expect(confidenceTierFor({})).toBe("confident")
    expect(confidenceTierFor({ confidence: Number.NaN })).toBe("confident")
  })
})

describe("confidenceSummaryOf", () => {
  it("counts each question exactly once", () => {
    const summary = confidenceSummaryOf([
      { confidence: 0.98 },
      { confidence: 0.95 },
      { confidence: 0.6 },
      { confidence: 0.99, reviewReason: "Two answers given" },
    ])
    expect(summary).toEqual({ confident: 2, uncertain: 1, needsReview: 1 })
    expect(summary.confident + summary.uncertain + summary.needsReview).toBe(4)
  })

  it("returns zeroes for a paper with no questions", () => {
    expect(confidenceSummaryOf([])).toEqual({ confident: 0, uncertain: 0, needsReview: 0 })
  })
})
