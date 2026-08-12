import { useQuery, type UseQueryResult } from "@tanstack/react-query"
import { request } from "@/lib/api"
import type { AdminSchoolList } from "@/lib/schoolTypes"

/*
 * React-query hooks wrapping `/api/school/*` (`lemely/web/routers/school.py`),
 * gated to `school_admin` alone. Same conventions as useMeApi.ts: one hook per
 * endpoint, no `fallback` passed to `request()`.
 */

/**
 * `GET /api/school/seats` — every school the authenticated admin administers.
 *
 * Consumed by T-12's audience selector, which needs a real `schoolId` for a
 * school-wide announcement (`AnnouncementCreateRequest.schoolId` is required
 * whenever `schoolWide` is true, because an admin can administer several
 * schools). This route already existed and is the only client-reachable source
 * of the caller's school memberships — do not add a second one, and do not
 * enrich `/api/me/profile` with schools to avoid it.
 *
 * `enabled` gates the fetch on the caller actually being a `school_admin`: any
 * other role gets a 403 here, and firing it for every teacher would put a
 * permanent error in the query cache behind a control they can't use anyway.
 */
export function useAdminSchools(enabled: boolean): UseQueryResult<AdminSchoolList, Error> {
  return useQuery({
    queryKey: ["school", "seats"],
    queryFn: () => request<AdminSchoolList>("/school/seats"),
    enabled,
  })
}
