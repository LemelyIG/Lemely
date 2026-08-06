import { useQuery, type UseQueryResult } from "@tanstack/react-query"
import { request } from "@/lib/api"
import type { Profile } from "@/lib/meTypes"

/*
 * React-query hooks wrapping `/api/me/*` (`lemely/web/routers/me.py`), reachable
 * by every authenticated role. Follows useStudentApi.ts's conventions: one hook
 * per endpoint, no `fallback` passed to `request()` — a real backend/auth
 * failure must surface as a query error the screen can render, never silently
 * resolve to empty data.
 */

export function useProfile(): UseQueryResult<Profile, Error> {
  return useQuery({
    queryKey: ["me", "profile"],
    queryFn: () => request<Profile>("/me/profile"),
  })
}
