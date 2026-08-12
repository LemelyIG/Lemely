import { useQuery, type UseQueryResult } from "@tanstack/react-query"
import { request } from "@/lib/api"
import type {
  Leaderboard,
  LeaderboardBasis,
  LeaderboardScope,
  StudentClassList,
} from "@/lib/leaderboardTypes"

/*
 * React-query hooks over S-29's endpoints (P5.3 chunk B, P5.4, D5.14 §1).
 *
 * Follows useAnnouncementApi.ts's conventions: one hook per endpoint and **no
 * `fallback` passed to `request()`**. A swallowed failure here would render as
 * an empty board, which is a *claim* — "nobody scored this week" — and not an
 * absence of data. A student told they are alone on a board their whole class
 * is on is worse served than one shown an error they can retry.
 */

const CLASSES_KEY = ["student", "classes"] as const

export interface LeaderboardParams {
  scope: LeaderboardScope
  basis: LeaderboardBasis
  /** Required by the backend when `scope === "class"`; ignored otherwise. */
  classId?: string | null
}

/**
 * The board for one scope/basis pair.
 *
 * `enabled` is false when a class board has no class selected: the backend
 * would 422, and firing a request we know is malformed would surface as an
 * error state for what is really "pick a class first".
 */
export function useLeaderboard(
  params: LeaderboardParams,
): UseQueryResult<Leaderboard, Error> {
  const { scope, basis, classId } = params
  const needsClass = scope === "class"
  return useQuery({
    // `classId` is in the key even for non-class scopes so switching class
    // and switching back cannot serve the first class's cached board.
    queryKey: ["student", "leaderboard", scope, basis, classId ?? null] as const,
    queryFn: () => {
      const search = new URLSearchParams({ scope, basis })
      if (needsClass && classId) search.set("class_id", classId)
      return request<Leaderboard>(`/student/leaderboard?${search.toString()}`)
    },
    enabled: !needsClass || Boolean(classId),
  })
}

/**
 * The caller's own classes, for the class-scope selector (D5.14 §1).
 *
 * Its own endpoint rather than a field on the board response: the selector has
 * to be populated *before* a class board can be requested at all, so deriving
 * it from a board would be circular.
 */
export function useMyClasses(): UseQueryResult<StudentClassList, Error> {
  return useQuery({
    queryKey: CLASSES_KEY,
    queryFn: () => request<StudentClassList>("/student/classes"),
  })
}
