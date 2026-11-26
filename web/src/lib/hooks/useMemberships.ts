import { useQuery, type UseQueryResult } from "@tanstack/react-query"
import { ApiError, request } from "@/lib/api"
import { TEAM_PERMISSIONS, type AssistantRole, type TeamPermission, type WireMembership } from "@/lib/billingTypes"

/*
 * The teams the signed-in teacher assists (`GET /api/teacher/team/memberships`), on its own.
 *
 * It is a separate module from `useTeamApi.ts` on purpose. The teacher portal's shell reads this
 * list to offer "Working as" (`components/acting/acting-context.tsx`), and the shell ships in the
 * entry chunk, which has a 150KB budget. `useTeamApi.ts` brings the whole team screen's adapters
 * and models with it; this brings a `request` call and a constant. `useTeamApi.ts` re-exports
 * both names, so every other caller is unchanged.
 */

/** A team the signed-in teacher assists. */
export interface JoinedTeam {
  memberId: string
  /** The lead teacher's user id: what `X-Lemely-Acting-Teacher` carries to act for this team. */
  teacherId: string
  teacherName: string
  role: AssistantRole
  /** What this assistant may do on that team now, as the server computed it. Unknown names dropped. */
  permissions: TeamPermission[]
  /**
   * False while the lead holds school data (`MembershipDTO.available`). The team stays listed, but
   * acting for it is refused with `team_lead_unavailable`, so the UI does not offer to.
   */
  available: boolean
}

export const fetchMemberships = () => request<{ memberships: WireMembership[] }>("/teacher/team/memberships")

/** Under `["team"]`, so joining a team (which invalidates that prefix) refreshes this list too. */
export const MEMBERSHIPS_KEY = ["team", "memberships"] as const

/**
 * `enabled: false` for an account that cannot hold a membership (a school admin in the teacher
 * portal): the route is teacher-only, so asking would only collect a 403. A refusal or a bad
 * request will not change on a retry; a server or network failure gets one.
 */
export function useMemberships(options: { enabled?: boolean } = {}): UseQueryResult<JoinedTeam[], Error> {
  return useQuery({
    queryKey: MEMBERSHIPS_KEY,
    retry: (failureCount, error) => !(error instanceof ApiError && error.status >= 400 && error.status < 500) && failureCount < 1,
    enabled: options.enabled ?? true,
    queryFn: async () => {
      const { memberships } = await fetchMemberships()
      return memberships.map((m) => ({
        memberId: m.memberId,
        teacherId: m.teacherId,
        teacherName: m.teacherName,
        role: m.role,
        permissions: TEAM_PERMISSIONS.filter((p) => m.effectivePermissions.includes(p)),
        // Only an explicit `false` makes a team unavailable, so a response without the field (an
        // older server) leaves it selectable, as it always was.
        available: m.available !== false,
      }))
    },
  })
}
