import { createContext, useContext } from "react"
import type { TeamPermission } from "@/lib/billingTypes"
import { teamPermissionDeniedMessage } from "@/lib/actingTeacher"
import type { JoinedTeam } from "@/lib/hooks/useMemberships"

/*
 * The "working as" context and its hooks, apart from the provider so that
 * `acting-context.tsx` exports only a component (Fast Refresh) and a screen that only reads the
 * role does not import the provider's data hooks. See `acting-context.tsx` for what the provider
 * guarantees.
 */

export interface ActingTeacherValue {
  /** The teams this teacher assists, empty until loaded (and for anyone who assists nobody). */
  memberships: readonly JoinedTeam[]
  /** The team being acted for, or `null` when working as oneself. */
  lead: JoinedTeam | null
  acting: boolean
  /** Whether the current role allows `permission`. Always true when working as oneself. */
  can: (permission: TeamPermission) => boolean
  /** Act for the lead whose user id this is, or pass `null` to work as oneself again. */
  choose: (teacherId: string | null) => void
  /** Why the last choice was dropped, until dismissed. */
  notice: string | null
  dismissNotice: () => void
}

export const NOT_ACTING: ActingTeacherValue = {
  memberships: [],
  lead: null,
  acting: false,
  can: () => true,
  choose: () => undefined,
  notice: null,
  dismissNotice: () => undefined,
}

export const ActingTeacherContext = createContext<ActingTeacherValue>(NOT_ACTING)

/** Who the teacher is working as. Outside the provider (tests, other portals) it is always "oneself". */
export function useActingTeacher(): ActingTeacherValue {
  return useContext(ActingTeacherContext)
}

/** Whether the current role may do `permission`. The one-line check for a button. */
export function useCan(permission: TeamPermission): boolean {
  return useContext(ActingTeacherContext).can(permission)
}

/** The sentence for a control the role lacks, or `null` when the control is allowed. */
export function useDeniedReason(permission: TeamPermission): string | null {
  const { can, lead } = useContext(ActingTeacherContext)
  return can(permission) ? null : teamPermissionDeniedMessage(lead?.teacherName ?? null)
}

