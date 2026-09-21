import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query"
import { ApiError, request } from "@/lib/api"
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
    onSuccess: (data, { attemptId, questionResultId }) => {
      queryClient.setQueryData(selfReviewKey(attemptId, questionResultId), data)
      queryClient.invalidateQueries({ queryKey: ["student", "overview"] })
      queryClient.invalidateQueries({ queryKey: ["student", "subject"] })
      queryClient.invalidateQueries({ queryKey: ["student", "result"] })
    },
    // A 409 means the server already holds a pass for this question — the
    // cached `not_started` view is now a lie, and re-offering the form can
    // only 409 again. A non-`ApiError` failure (a lost response, a dropped
    // connection) is worse: the client genuinely does not know whether the
    // POST landed, and a refetch is the only cheap way to find out. Either
    // way, invalidate so the panel converges on the server's own truth
    // instead of leaving the student staring at a form for a pass already
    // recorded (Task 13/14 review, IMP-1).
    onError: (error, { attemptId, questionResultId }) => {
      if (!(error instanceof ApiError) || error.status === 409) {
        queryClient.invalidateQueries({
          queryKey: selfReviewKey(attemptId, questionResultId),
        })
      }
    },
  })
}
