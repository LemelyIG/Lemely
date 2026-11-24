import {
  useMutation,
  useQueries,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query"
import { request } from "@/lib/api"
import { RUNS_LIMIT, practiceHubKeys, practiceHubPaths } from "@/lib/practiceHubKeys"
import type { PastPapers, PracticeRuns } from "@/lib/practiceHubTypes"
import type { CreatePracticeResponse, PracticeTopics } from "@/lib/practiceTypes"

/*
 * Practice tab hooks (L4). Same convention as `usePracticeApi.ts`: no
 * `fallback` passed to `request()`, so a backend failure is a query error the
 * screen renders, never silently empty data.
 */

/** `GET /api/student/practice/runs`: "Recent". */
export function usePracticeRuns(limit = RUNS_LIMIT): UseQueryResult<PracticeRuns, Error> {
  return useQuery({
    queryKey: practiceHubKeys.runs(limit),
    queryFn: () => request<PracticeRuns>(practiceHubPaths.runs(limit)),
  })
}

/** Topics for every subject at once (win marks back). Shares the cache key with `usePracticeTopics`. */
export function usePracticeTopicsMany(subjectCodes: readonly string[]): UseQueryResult<PracticeTopics, Error>[] {
  return useQueries({
    queries: subjectCodes.map((code) => ({
      queryKey: practiceHubKeys.topics(code),
      queryFn: () => request<PracticeTopics>(practiceHubPaths.topics(code)),
      enabled: !!code,
    })),
  })
}

/** `GET /api/student/practice/papers/{code}`. */
export function usePastPapers(subjectCode: string): UseQueryResult<PastPapers, Error> {
  return useQuery({
    queryKey: practiceHubKeys.papers(subjectCode),
    queryFn: () => request<PastPapers>(practiceHubPaths.papers(subjectCode)),
    enabled: !!subjectCode,
  })
}

/** `POST /api/student/practice/papers/{paperId}`. On success, Recent refreshes. */
export function useCreateFromPaper(): UseMutationResult<
  CreatePracticeResponse,
  Error,
  { paperId: string; timed: boolean }
> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ paperId, timed }) =>
      request<CreatePracticeResponse>(practiceHubPaths.createFromPaper(paperId), {
        method: "POST",
        body: JSON.stringify({ timed }),
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: practiceHubKeys.runsAll })
    },
  })
}
