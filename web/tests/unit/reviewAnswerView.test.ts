import { describe, expect, it } from "vitest"
import type { ReviewItemDetail } from "@/lib/teacherTypes"
import { answerViewFromReviewItem } from "@/portals/teacher/screens/review/answerView"

function detail(over: Partial<ReviewItemDetail> = {}): ReviewItemDetail {
  return {
    itemId: "i1", source: "student_attempt", attemptId: "a1", paperId: null, questionResultId: "qr1",
    studentId: "s1", studentDisplayName: "Layla Hassan", classId: "c1", className: "10B",
    subjectCode: "0580", paperNumber: 4, paperVariant: 2, sessionMonth: "May/June", sessionYear: 2025,
    questionId: "4(b)", reason: "low_confidence", status: "open", createdAt: "2026-11-14T10:00:00Z",
    waitingHours: 2, aiAwardedMarks: 4, maximumMarks: 5, confidenceScore: 0.64, reviewReason: "confidence 0.64 below review threshold 0.90",
    studentAnswer: "x = 3y + 2", expectedAnswer: "y = 1/3 or -5/3", topic: "Quadratics", matchedPointIds: ["p1"],
    feedback: "Sign slip in the constant.", markerSource: "ai", isOverridden: false, teacherAwardedMarks: null,
    teacherNote: null, teacherBreakdown: null, overriddenBy: null, overriddenAt: null, resolutionNote: null,
    resolvedBy: null, resolvedAt: null, points: [], hasSourceBox: true, sourcePage: 6,
    ...over,
  } as ReviewItemDetail
}

describe("answerViewFromReviewItem", () => {
  it("builds the header, page label and scheme wording", () => {
    const v = answerViewFromReviewItem(detail())
    expect(v.title).toBe("Layla Hassan · Q4(b)")
    expect(v.subtitle).toBe("10B · 0580/42 · m/j 2025")
    expect(v.pageLabel).toBe("Page 6 · 0580/42")
    expect(v.studentHref).toBe("/teacher/students/s1")
    expect(v.scheme).toEqual({ expected: "y = 1/3 or -5/3", topic: "Quadratics" })
    expect(v.notes).toEqual({ reason: "confidence 0.64 below review threshold 0.90", feedback: "Sign slip in the constant." })
    expect(v.canAdjust).toBe(true)
    expect(v.cannotAdjustReason).toBeNull()
  })
  it("treats console papers honestly (K7, I16)", () => {
    const v = answerViewFromReviewItem(detail({ source: "console_paper", studentId: null, className: null, questionResultId: null, hasSourceBox: false, sourcePage: null }))
    expect(v.studentHref).toBeNull()
    expect(v.subtitle.startsWith("Grading console · ")).toBe(true)
    expect(v.hasScan).toBe(false)
    expect(v.pageLabel).toBeNull()
    expect(v.canAdjust).toBe(false)
    expect(v.cannotAdjustReason).toBe(
      "Papers marked in the grading console store no per-question result to record a new mark on. Accept as-is, or re-run the paper from the console.",
    )
  })
  it("lists only self-marked points as Student said lines (I12)", () => {
    const v = answerViewFromReviewItem(
      detail({
        points: [
          { markPointId: "p1", pointText: "Expands", awarded: true, studentSelfmark: null, studentEvidence: null, evidenceVerdict: null, verdict: null, evidenceSpan: "", ecfApplied: false, rationale: null, ordinal: 0, markType: "M", tariff: 1, groupKey: null, groupMaxMarks: null },
          { markPointId: "p2", pointText: "Constant", awarded: false, studentSelfmark: true, studentEvidence: "I wrote -4.", evidenceVerdict: null, verdict: null, evidenceSpan: "", ecfApplied: false, rationale: null, ordinal: 1, markType: "A", tariff: 1, groupKey: null, groupMaxMarks: null },
        ],
      }),
    )
    expect(v.selfReview).toEqual([{ code: "A1", claim: "Claims earned", evidence: "I wrote -4.", judge: "Not yet judged" }])
  })
  it("carries the read-only record for a closed item (I18, I19)", () => {
    const v = answerViewFromReviewItem(detail({ status: "resolved", isOverridden: true, teacherAwardedMarks: 3, teacherNote: "Unit missing", overriddenAt: "2026-11-14T11:00:00Z", resolutionNote: "checked" }))
    expect(v.status).toBe("resolved")
    expect(v.correction).toEqual({ marks: 3, note: "Unit missing", at: "2026-11-14T11:00:00Z" })
    expect(v.resolutionNote).toBe("checked")
  })
  it("flags integrity items", () => {
    expect(answerViewFromReviewItem(detail({ reason: "plagiarism_flag", confidenceScore: null })).integrity).toBe(true)
  })
})

describe("answerViewFromReviewItem clamp note", () => {
  it("surfaces clampNote whenever Lemely's mark is above the maximum", () => {
    expect(answerViewFromReviewItem(detail({ aiAwardedMarks: 7, maximumMarks: 5 })).clampNote).toBe(
      "Lemely gave 7, above the maximum of 5, so it is shown as 5",
    )
    expect(answerViewFromReviewItem(detail()).clampNote).toBeNull()
  })
})
