import { useQuery, type UseQueryResult } from "@tanstack/react-query"
import { request } from "@/lib/api"
import type { ClassList, ReviewQueueList } from "@/lib/teacherTypes"

/*
 * The two teacher queries the portal shell itself reads: the class list (sidebar, and the lead
 * check in `TeacherLayout`) and the review-queue count (sidebar and bottom-nav badge).
 *
 * Apart from `useTeacherApi.ts` for bundle size. The shell ships in the entry chunk (150KB gzipped
 * budget); importing either hook from the 50KB `useTeacherApi.ts` dragged every teacher hook,
 * most of which only a lazily loaded screen uses, into it. `useTeacherApi.ts` re-exports both
 * names, so no other caller changes.
 */

/** `GET /teacher/classes` (T-01/T-02). */
export function useTeacherClasses(): UseQueryResult<ClassList, Error> {
  return useQuery({
    queryKey: ["teacher", "classes"],
    queryFn: () => request<ClassList>("/teacher/classes"),
  })
}

/**
 * `GET /teacher/review?class_id=&reason=&min_age_hours=&limit=&cursor=`
 * (T-07/T-09). `classId`/`reason`/`minAgeHours` are real server-side filters
 * (`ReviewService.list_queue`) — never applied client-side against an
 * unfiltered fetch. A malformed `classId` 422s on the backend; the screen
 * renders that as a normal query error rather than hiding it.
 *
 * `limit` (server default 50, 1..200) bounds the page size; `cursor`, when
 * given, continues a previous page — both are Task 9's keyset pagination,
 * consumed by Task 11's "Load more" (`Review.tsx`). Both are part of the
 * query key so a page fetched under one cursor is cached separately from
 * every other page, the same as the three filters already are.
 *
 * `staleTime` (C3d) defaults to react-query's own default (effectively
 * "always stale") when omitted, matching every existing caller's behaviour
 * unchanged; `useReviewQueueCount` passes `60_000` so the sidebar/bottom-nav
 * badge doesn't refetch on every mount or focus for a number that is a hint,
 * not a live counter.
 */
export function useReviewQueue(params?: {
  classId?: string
  reason?: string
  minAgeHours?: number
  limit?: number
  cursor?: string
  staleTime?: number
}): UseQueryResult<ReviewQueueList, Error> {
  const classId = params?.classId
  const reason = params?.reason
  const minAgeHours = params?.minAgeHours
  const limit = params?.limit
  const cursor = params?.cursor
  const query = new URLSearchParams()
  if (classId) query.set("class_id", classId)
  if (reason) query.set("reason", reason)
  if (minAgeHours !== undefined) query.set("min_age_hours", String(minAgeHours))
  if (limit !== undefined) query.set("limit", String(limit))
  if (cursor) query.set("cursor", cursor)
  const qs = query.toString()
  return useQuery({
    queryKey: [
      "teacher",
      "review",
      "queue",
      classId ?? null,
      reason ?? null,
      minAgeHours ?? null,
      limit ?? null,
      cursor ?? null,
    ],
    queryFn: () => request<ReviewQueueList>(`/teacher/review${qs ? `?${qs}` : ""}`),
    staleTime: params?.staleTime,
  })
}
