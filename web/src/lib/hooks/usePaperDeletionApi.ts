import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query"
import { request } from "@/lib/api"
import type { DeletedPapers } from "@/lib/studentTypes"

/*
 * React-query hooks wrapping the student paper-deletion API (Task 8,
 * `lemely/web/routers/student.py`). File location per the plan review's
 * amendment (Minor 4): alongside `useSelfReviewApi.ts`, not under
 * `portals/student/hooks/` — every other student API wrapper lives in
 * `lib/hooks/`, and a second location would just be a place the next reader
 * has to remember to also check. Follows the same conventions those hooks
 * do: one hook per endpoint, no `fallback` passed to `request()`, so a real
 * failure (including the 409 hold and the 410 past-window) reaches the
 * caller as an error rather than resolving to empty data.
 */

export const deletedPapersKey = ["student", "attempts", "deleted"] as const

/** `GET /student/attempts/deleted` — one row per upload (R7), newest first. */
export function useDeletedPapers(): UseQueryResult<DeletedPapers, Error> {
  return useQuery({
    queryKey: deletedPapersKey,
    queryFn: () => request<DeletedPapers>("/student/attempts/deleted"),
  })
}

/**
 * `DELETE /student/attempts/{attemptId}` → 204. Refusals arrive as errors
 * (409 hold with `deletableFrom`, 409 "only uploaded papers", 404) for the
 * caller to render with `deletionRefusal` — never pre-signalled, never
 * swallowed here.
 *
 * On success, invalidates the overview and subject queries rather than
 * trusting the caller's own optimistic row removal for anything beyond that
 * one row: `/student/result/{paperId}` is a **positional** address (design
 * §2.1) — the paper list it indexes into has shifted, so any neighbouring
 * link built from the pre-delete list is now unsafe to reuse. A screen that
 * wants to navigate away after a delete must wait for this invalidation's
 * refetch to settle first, not reuse an index computed before it.
 */
export function useDeletePaper(): UseMutationResult<void, Error, { attemptId: string }> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ attemptId }: { attemptId: string }) =>
      request<void>(`/student/attempts/${encodeURIComponent(attemptId)}`, { method: "DELETE" }),
    // Returned (not fire-and-forget): `mutateAsync` only resolves once this
    // promise settles, which is exactly what the positional-URL trap needs —
    // a caller that navigates after `await mutateAsync(...)` waits for these
    // refetches rather than reusing a pre-delete index the instant the
    // DELETE itself returns.
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: ["student", "overview"] }),
        queryClient.invalidateQueries({ queryKey: ["student", "subject"] }),
        queryClient.invalidateQueries({ queryKey: deletedPapersKey }),
      ]),
  })
}

/**
 * `POST /student/attempts/{attemptId}/restore` → 204; 410 once past the
 * window (or otherwise unrestorable), 404 for anything else not this
 * student's own. Invalidates the same surfaces a delete does — a restore is
 * a delete undone, so every screen a delete moved needs to move back.
 */
export function useRestorePaper(): UseMutationResult<void, Error, { attemptId: string }> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ attemptId }: { attemptId: string }) =>
      request<void>(`/student/attempts/${encodeURIComponent(attemptId)}/restore`, {
        method: "POST",
      }),
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: ["student", "overview"] }),
        queryClient.invalidateQueries({ queryKey: ["student", "subject"] }),
        queryClient.invalidateQueries({ queryKey: deletedPapersKey }),
      ]),
  })
}
