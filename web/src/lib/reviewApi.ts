import { request } from "@/lib/api"
import type { DismissReviewRequest, ResolveReviewRequest, ReviewQueueItem } from "@/lib/teacherTypes"

/**
 * One teacher decision on one review item, held for the undo window before it
 * is sent (`portals/teacher/screens/review/pendingDecisions.ts`). `label` is
 * the toast copy subject ("Q4(b)"); `changed` says the mark moved.
 */
export type ReviewDecision =
  | { kind: "resolve"; itemId: string; label: string; changed: boolean; body: ResolveReviewRequest }
  | { kind: "dismiss"; itemId: string; label: string; body: DismissReviewRequest }

/**
 * POST the decision. `keepalive` is set when the page is being hidden or left
 * (`pagehide`), so a decision still inside its undo window is not lost when
 * the teacher closes the tab. The browser caps keepalive bodies at 64 KB;
 * these are a few hundred bytes.
 */
export function postReviewDecision(d: ReviewDecision, opts: { keepalive?: boolean } = {}): Promise<ReviewQueueItem> {
  const path = d.kind === "dismiss" ? `/teacher/review/${d.itemId}/dismiss` : `/teacher/review/${d.itemId}/resolve`
  return request<ReviewQueueItem>(path, {
    method: "POST",
    body: JSON.stringify(d.body),
    keepalive: opts.keepalive,
  })
}
