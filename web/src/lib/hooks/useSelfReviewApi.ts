import { useQuery, type UseQueryResult } from "@tanstack/react-query"
import { request } from "@/lib/api"
import type { QuestionResult } from "@/lib/studentTypes"

/*
 * React-query hooks wrapping the student self-review API
 * (`lemely/web/routers/student_self_review.py`). Follows `useStudentApi.ts`'s
 * conventions: one hook per endpoint, no `fallback` passed to `request()`.
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
