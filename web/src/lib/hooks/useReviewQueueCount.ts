import { useReviewQueue } from "./useTeacherApi"

/**
 * Queue-depth count for badges (C3d) — the sidebar "Review" nav item and the
 * bottom-nav Review tab (`portals/teacher/index.tsx`).
 *
 * Built directly on `useReviewQueue({ limit: 1 })` rather than a
 * hand-rolled fetch: `limit: 1` means the badge never pulls a full page of
 * items just to read `total`, and calling the same hook `useReviewQueue`
 * itself uses means this can never drift from its query-key shape
 * (`["teacher", "review", "queue", classId, reason, minAgeHours, limit,
 * cursor]`, `useTeacherApi.ts`) — with every filter left at its unfiltered
 * default, that key shares the `["teacher", "review", "queue"]` prefix the
 * full, unfiltered queue page's own `useReviewQueue()` call also builds on.
 * Two things follow from sharing that prefix:
 *
 *   - the sidebar item and the bottom-nav tab, each calling this hook, land
 *     on the exact same cache entry and dedupe to one network request
 *     (React Query dedupes identical query keys automatically);
 *   - `useResolveReviewItem`/`useDismissReviewItem`/`useBulkApproveReview`'s
 *     shared `invalidateQueries({ queryKey: ["teacher", "review"] })`
 *     (prefix match, `useTeacherApi.ts`) refreshes this badge in lockstep
 *     with the full queue page, with no second invalidation target to keep
 *     in sync.
 *
 * Returns `null` while loading or on error, so a nav site renders no badge
 * at all rather than a wrong or stale one — never `0` as a loading stand-in.
 */
export function useReviewQueueCount(): number | null {
  const { data, isPending, isError } = useReviewQueue({ limit: 1, staleTime: 60_000 })
  if (isPending || isError || data === undefined) return null
  return data.total
}
