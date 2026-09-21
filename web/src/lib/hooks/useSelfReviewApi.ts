import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query"
import { ApiError, request } from "@/lib/api"
import { clearDraft } from "@/lib/selfReview"
import type { SelfReview, SelfReviewRevealed, SelfReviewSubmission } from "@/lib/selfReviewTypes"
import type { QuestionResult } from "@/lib/studentTypes"

/*
 * React-query hooks wrapping the student self-review API
 * (`lemely/web/routers/student_self_review.py`). Follows `useStudentApi.ts`'s
 * conventions: one hook per endpoint, no `fallback` passed to `request()`, so
 * a real failure surfaces as an error the screen/panel renders rather than as
 * empty data.
 */

export const attemptQuestionsKey = (attemptId: string) =>
  ["student", "attemptQuestions", attemptId] as const

/**
 * `GET /student/attempts/{attemptId}/questions` — the per-question rows of a
 * history-sourced result. Disabled without an attempt id (a file-store
 * record), in which case `PaperResult` keeps its honest "no per-question
 * detail" state.
 */
export function useAttemptQuestions(
  attemptId: string | null | undefined,
): UseQueryResult<QuestionResult[], Error> {
  return useQuery({
    queryKey: attemptQuestionsKey(attemptId ?? ""),
    queryFn: () =>
      request<QuestionResult[]>(`/student/attempts/${encodeURIComponent(attemptId ?? "")}/questions`),
    enabled: !!attemptId,
  })
}

export const selfReviewKey = (attemptId: string, questionResultId: string) =>
  ["student", "selfReview", attemptId, questionResultId] as const

function selfReviewPath(attemptId: string, questionResultId: string): string {
  return `/student/attempts/${encodeURIComponent(attemptId)}/questions/${encodeURIComponent(questionResultId)}/self-review`
}

/**
 * `GET` `/student/attempts/{a}/questions/{q}/self-review`. A 404 is a real,
 * final answer ("no point rows: not self-reviewable"), so it is not
 * retried; `SelfReviewPanel` renders `UNAVAILABLE_COPY` for it. Any other
 * client error (401/403/422, ...) is just as final here — the route answers
 * cross-student access with 404 rather than 403, so a genuine 4xx below 429
 * is not a transient condition a retry can fix (Task 13/14 review, NIT-5).
 */
export function useSelfReview(
  attemptId: string,
  questionResultId: string,
): UseQueryResult<SelfReview, Error> {
  return useQuery({
    queryKey: selfReviewKey(attemptId, questionResultId),
    queryFn: () => request<SelfReview>(selfReviewPath(attemptId, questionResultId)),
    enabled: !!attemptId && !!questionResultId,
    retry: (failureCount, error) =>
      !(error instanceof ApiError && error.status < 500 && error.status !== 429) &&
      failureCount < 2,
  })
}

export interface SubmitSelfReviewInput {
  attemptId: string
  questionResultId: string
  submission: SelfReviewSubmission
}

/**
 * `POST` `/student/attempts/{a}/questions/{q}/self-review`. On success the
 * revealed view replaces the cached pending one in place, and every
 * total-bearing student surface is invalidated: a granted self-mark moves
 * the attempt's marks, percentage and grade (spec D5).
 */
export function useSubmitSelfReview(): UseMutationResult<
  SelfReviewRevealed,
  Error,
  SubmitSelfReviewInput
> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ attemptId, questionResultId, submission }: SubmitSelfReviewInput) =>
      request<SelfReviewRevealed>(selfReviewPath(attemptId, questionResultId), {
        method: "POST",
        body: JSON.stringify(submission),
      }),
    // `onSuccess` here is option-level (passed to `useMutation`, not to a
    // particular `mutate()` call), which matters for `clearDraft`: a
    // per-call callback does not fire once its caller has unmounted
    // (verified against @tanstack/query-core 5.102.8's `MutationObserver`
    // — a per-call `onSuccess` is a no-op after unmount, the option-level
    // one still runs), and `QuestionRow` unmounts `SelfReviewPanel` the
    // instant its row collapses (`question-row.tsx:186`). A student who
    // submits and immediately collapses the row (or switches tabs, which
    // also unmounts it) must still have their draft cleared — otherwise it
    // sits in `sessionStorage` for the life of the tab after the one pass
    // it belonged to (Task 13/14 re-review, R-5).
    onSuccess: (data, { attemptId, questionResultId }) => {
      queryClient.setQueryData(selfReviewKey(attemptId, questionResultId), data)
      clearDraft(attemptId, questionResultId)
      queryClient.invalidateQueries({ queryKey: ["student", "overview"] })
      queryClient.invalidateQueries({ queryKey: ["student", "subject"] })
      queryClient.invalidateQueries({ queryKey: ["student", "result"] })
    },
    // Invalidate the self-review query on ANY submit failure, unconditionally
    // (Task 13/14 re-review, R-9 — widened from the first fix's 409-or-
    // non-ApiError condition). A 409 means the server already holds a pass;
    // a non-`ApiError` failure (a lost response, a dropped connection) means
    // the client genuinely does not know whether the POST landed; and a
    // gateway failure (502/504/408) is an `ApiError` that looks like a clean
    // rejection but may equally have committed server-side before the
    // gateway gave up — the same "don't know" condition as a network error.
    // A refetch is cheap and always converges on the server's own truth, so
    // there is no case where invalidating is wrong; the only case where it
    // was previously skipped (a genuine app-level 500, an atomic rollback)
    // just refetches back to the same `not_started` view it already had.
    //
    // This composes with the panel's `isLoadingError` check
    // (`SelfReviewPanel.tsx`, R-2): the refetch this triggers can itself
    // fail (offline), and `isLoadingError` (not `isError`) is what keeps a
    // completed, filled-in form on screen through that failure rather than
    // replacing it with a load-error screen.
    onError: (_error, { attemptId, questionResultId }) => {
      queryClient.invalidateQueries({
        queryKey: selfReviewKey(attemptId, questionResultId),
      })
    },
  })
}
