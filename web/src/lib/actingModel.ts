import { PERMISSION_COPY, ROLE_COPY } from "@/lib/assistantRoles"
import type { AssistantRole, TeamPermission } from "@/lib/billingTypes"

/*
 * What the "working as" UI says, as plain functions so the wording can be tested without a DOM.
 * The mechanics (who is acted for, which requests carry the header) are in `lib/actingTeacher.ts`.
 */

/** The switcher's option for the caller's own account. */
export const SELF_OPTION_ID = "self"

/** The least a membership row needs for the UI to name it. */
export interface TeamLabelSource {
  teacherName: string
  role: AssistantRole
}

/** "Mr Hassan (Marker)": the lead and the role, which is all the person needs to pick by. */
export function leadLabel(team: TeamLabelSource): string {
  return `${team.teacherName} (${ROLE_COPY[team.role].label})`
}

/** The switcher's options: "Me" first, then each team the caller assists. Ids are the lead's user id. */
export function switcherOptions(
  teams: readonly (TeamLabelSource & { teacherId: string; available?: boolean })[],
): { id: string; label: string; disabled?: boolean; description?: string }[] {
  return [
    { id: SELF_OPTION_ID, label: "Me" },
    ...teams.map((t) =>
      t.available === false
        ? { id: t.teacherId, label: leadLabel(t), disabled: true, description: "Not available right now" }
        : { id: t.teacherId, label: leadLabel(t) },
    ),
  ]
}

/**
 * The permissions a teacher screen can actually gate on. `view_usage` is left out on purpose: no
 * teacher screen is behind it (usage and billing are the caller's own, never the lead's).
 */
export const SCREEN_PERMISSIONS: readonly TeamPermission[] = [
  "mark",
  "regrade",
  "generate_quiz",
  "manage_classes",
  "view_results",
  "manage_students",
]

/** The screen permissions a role does not carry, in catalogue order. */
export function lackedPermissions(granted: readonly TeamPermission[]): TeamPermission[] {
  return SCREEN_PERMISSIONS.filter((p) => !granted.includes(p))
}

const lowerFirst = (s: string) => s.charAt(0).toLowerCase() + s.slice(1)

/**
 * One sentence saying what the role cannot do, or `null` when it can do everything a screen
 * offers. Said as a lack because that is what the person needs to know before reaching for a
 * button that is not there.
 */
export function lackedSummary(granted: readonly TeamPermission[]): string | null {
  const lacked = lackedPermissions(granted).map((p) => lowerFirst(PERMISSION_COPY[p]))
  if (lacked.length === 0) return null
  const list =
    lacked.length === 1 ? lacked[0] : `${lacked.slice(0, -1).join(", ")} or ${lacked[lacked.length - 1]}`
  return `Your role can't ${list}.`
}

export { leadUnavailableNotice, membershipEndedNotice, MEMBERSHIP_UNCONFIRMED_NOTICE, ownAccountNote } from "@/lib/actingNotices"
