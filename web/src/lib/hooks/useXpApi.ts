import { useQuery, type UseQueryResult } from "@tanstack/react-query"
import { request } from "@/lib/api"
import type { XpProfile } from "@/lib/xpTypes"

/*
 * React-query hook over `GET /api/student/xp` (P5.8 chunk A, D5.13).
 *
 * One query for the whole of S-31, matching the route: the backend resolves
 * `today` once for all four reads, so a request crossing midnight in Cairo
 * cannot return a week and a calendar that disagree. Splitting this into
 * several hooks would reintroduce exactly that race on the client.
 *
 * No `fallback` passed to `request()`, per this directory's convention — a
 * swallowed failure would render as "0 XP, no streak", which is a claim about
 * a student's work rather than an absence of data, and the most discouraging
 * possible thing to show someone who has been studying.
 */

export function useXpProfile(): UseQueryResult<XpProfile, Error> {
  return useQuery({
    queryKey: ["student", "xp"] as const,
    queryFn: () => request<XpProfile>("/student/xp"),
  })
}
