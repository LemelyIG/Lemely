import { describe, expect, it } from "vitest"

import { mergeReviewPages } from "@/portals/teacher/screens/Review"
import type { ReviewQueueItem } from "@/lib/teacherTypes"

/*
 * Task 11 (B6c) — `mergeReviewPages` backs Review.tsx's "Load more" cursor
 * pagination (T-07's `GET /teacher/review` now returns `nextCursor`, T-09).
 * Pulled out as a pure function so the accumulate-vs-replace decision is
 * unit-testable without mounting the screen (`vitest.config.ts` is Node, no
 * jsdom — see that file's own header).
 */

function item(itemId: string): ReviewQueueItem {
  return {
    itemId,
    source: "student_attempt",
    attemptId: "attempt-1",
    paperId: null,
    questionResultId: null,
    studentId: "student-1",
    studentDisplayName: "Ada",
    classId: "class-1",
    className: "10A",
    subjectCode: "MATH",
    paperNumber: 1,
    paperVariant: 1,
    sessionMonth: "May",
    sessionYear: 2026,
    questionId: "q1",
    reason: "low_confidence",
    status: "open",
    createdAt: "2026-01-01T00:00:00Z",
    waitingHours: 1,
    aiAwardedMarks: 2,
    maximumMarks: 4,
    confidenceScore: 0.5,
  }
}

describe("mergeReviewPages", () => {
  it("replaces prev entirely when the key differs (a filter change)", () => {
    const prev = { key: "class-1|low_confidence|", items: [item("a"), item("b")] }
    const page = { key: "class-2||", items: [item("c")] }
    expect(mergeReviewPages(prev, page)).toEqual(page)
  })

  it("appends when the key matches (Load more on the same filters)", () => {
    const prev = { key: "k", items: [item("a"), item("b")] }
    const page = { key: "k", items: [item("c"), item("d")] }
    expect(mergeReviewPages(prev, page)).toEqual({ key: "k", items: [item("a"), item("b"), item("c"), item("d")] })
  })

  it("dedupes appended items by itemId", () => {
    const prev = { key: "k", items: [item("a"), item("b")] }
    const page = { key: "k", items: [item("b"), item("c")] }
    expect(mergeReviewPages(prev, page)).toEqual({ key: "k", items: [item("a"), item("b"), item("c")] })
  })

  it("starting from an empty prev just becomes the page", () => {
    const prev = { key: "", items: [] }
    const page = { key: "k", items: [item("a")] }
    expect(mergeReviewPages(prev, page)).toEqual(page)
  })

  it("an empty next page on the same key leaves items unchanged", () => {
    const prev = { key: "k", items: [item("a")] }
    const page = { key: "k", items: [] }
    expect(mergeReviewPages(prev, page)).toEqual({ key: "k", items: [item("a")] })
  })
})
