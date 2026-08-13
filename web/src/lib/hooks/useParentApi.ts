import { useQuery, type UseQueryResult } from "@tanstack/react-query"
import { request } from "@/lib/api"
import type {
  ChildList,
  ChildOverview,
  ChildWeaknesses,
  SubjectDetail,
} from "@/lib/parentTypes"

/*
 * React-query hooks wrapping `/api/parent/*` (`lemely/web/routers/parent.py`),
 * gated `require_role(parent)` server-side. Follows useTeacherApi.ts's
 * conventions: one hook per endpoint, no `fallback` passed to `request()` — a
 * real backend/auth failure must surface as a query error the screen renders,
 * never silently resolve to an empty child list. An empty list here means "no
 * children linked", which P-01 answers with a how-to-link explanation; a
 * fallback would make a 403 look like that same state.
 *
 * Every route is read-only (the parent portal has no mutations at all), so
 * there is nothing to invalidate and no mutation hook belongs in this file.
 * Linking/unlinking is student-side — see `useStudentApi.ts`.
 */

export function useChildren(): UseQueryResult<ChildList, Error> {
  return useQuery({
    queryKey: ["parent", "children"],
    queryFn: () => request<ChildList>("/parent/children"),
  })
}

export function useChildOverview(childId: string): UseQueryResult<ChildOverview, Error> {
  return useQuery({
    queryKey: ["parent", "children", childId],
    queryFn: () => request<ChildOverview>(`/parent/children/${childId}`),
  })
}

export function useChildSubject(
  childId: string,
  subjectCode: string,
): UseQueryResult<SubjectDetail, Error> {
  return useQuery({
    queryKey: ["parent", "children", childId, "subjects", subjectCode],
    queryFn: () =>
      request<SubjectDetail>(`/parent/children/${childId}/subjects/${subjectCode}`),
  })
}

/**
 * The subject already in cache, or `undefined` — never a request.
 *
 * P4.6 · the portal shell's breadcrumb needs one field of the subject detail
 * (its translated name) on the subject route, and it must not pay a second
 * request for it. `enabled: false` means react-query never fetches on this
 * observer's behalf, but the observer is still subscribed to the cache entry,
 * so when `SubjectDetail`'s own query resolves the crumb re-renders with the
 * name. `getQueryData` would have read the same value without subscribing, and
 * the crumb would have stayed on its fallback for the life of the screen.
 *
 * Same query key as `useChildSubject` on purpose: two keys for one resource is
 * how a cache stops being one.
 */
export function useCachedChildSubject(
  childId: string,
  subjectCode: string,
): SubjectDetail | undefined {
  return useQuery({
    queryKey: ["parent", "children", childId, "subjects", subjectCode],
    queryFn: () =>
      request<SubjectDetail>(`/parent/children/${childId}/subjects/${subjectCode}`),
    enabled: false,
  }).data
}

export function useChildWeaknesses(childId: string): UseQueryResult<ChildWeaknesses, Error> {
  return useQuery({
    queryKey: ["parent", "children", childId, "weaknesses"],
    queryFn: () => request<ChildWeaknesses>(`/parent/children/${childId}/weaknesses`),
  })
}
