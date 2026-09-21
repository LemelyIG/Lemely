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
 * retried; `SelfReviewPanel` renders `UNAVAILABLE_COPY` for it.
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
      !(error instanceof ApiError && error.status === 404) && failureCount < 2,
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
  })
}
