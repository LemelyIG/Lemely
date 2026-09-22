import { confidenceTierFor } from "./markingConfidence"
import type { QuestionResult } from "./types"

/*
 * C3a (Task 6). Pure filtering logic for `PaperResult`'s All / Lost /
 * Flagged tabs, moved out of the screen so it is testable without jsdom
 * (`web/vitest.config.ts` is Node-only — see `tests/unit/questionFilter.test.ts`).
 *
 * `markState` was previously a local function in `PaperResult.tsx`; its body
 * is unchanged, only its home moved.
 */

export type MarkState = "correct" | "partial" | "wrong"

/** correct = full marks, wrong = zero, partial = anything between. */
export function markState(q: QuestionResult): MarkState {
  if (q.maxMarks <= 0) return q.awardedMarks > 0 ? "correct" : "wrong"
  if (q.awardedMarks >= q.maxMarks) return "correct"
  if (q.awardedMarks <= 0) return "wrong"
  return "partial"
}

/**
 * A question needs a second look when the backend flagged it directly
 * (`reviewReason`, set independent of score — e.g. an integrity check), or
 * when its confidence bucket is the lowest tier `confidenceTierFor` produces
 * ("needs-review", `lib/markingConfidence.ts`). The two conditions overlap
 * today (a `reviewReason` also makes `confidenceTierFor` return
 * "needs-review"), but `reviewReason` is checked explicitly rather than
 * relying on that as an implementation detail of the tier function.
 *
 * `pendingTeacher === false` overrides both: it says no teacher review is
 * open for this question right now, so a `reviewReason` frozen from marking
 * time must not keep it in the Flagged tab (or its count) after a self-mark
 * has settled it — the same current-truth-over-frozen-flag rule
 * `confidenceTierFor` applies, checked explicitly here for the same reason
 * `reviewReason` is: this function must not depend on it as an
 * implementation detail of the tier function.
 */
export function isFlagged(q: QuestionResult): boolean {
  if (q.pendingTeacher === false) return false
  return q.reviewReason != null || confidenceTierFor(q) === "needs-review"
}

export type QuestionFilter = "all" | "lost" | "flagged"

/** `lost` = anything short of full marks; `flagged` = `isFlagged`. */
export function filterQuestions(
  questions: readonly QuestionResult[],
  filter: QuestionFilter,
): QuestionResult[] {
  switch (filter) {
    case "lost":
      return questions.filter((q) => markState(q) !== "correct")
    case "flagged":
      return questions.filter(isFlagged)
    case "all":
    default:
      return [...questions]
  }
}
