import { looksLikeTeamLeadUnavailable, looksLikeTeamPermissionDenied } from "@/lib/actingTeacher"
import type { TeamPermission } from "@/lib/billingTypes"

/*
 * Whether the lead being acted for can be worked for at all, judged from how the server answered the
 * lead's class list (the one read every teacher page leans on).
 *
 * Kept out of the portal shell's eager code on purpose: only the lazily loaded guard and banner use
 * it, and the shell is in the entry chunk (150KB gzipped budget).
 *
 * The server answers three different situations with 403s, and the client must not blur them:
 *   - `team_lead_unavailable`: the lead's team cannot be reached by assistants right now (school
 *     data). Nothing the assistant can change.
 *   - `team_permission_denied` while the role lacks `view_results`: the role cannot see this
 *     team's classes. The lead can change that.
 *   - `team_permission_denied` while the role has `view_results`: the membership changed after the
 *     list loaded. Treated like unavailable until the membership list catches up.
 */

export type LeadAccess = "ok" | "unavailable" | "no-view"

/**
 * Pages about the caller's own account whoever they act for: team, billing, settings, the
 * notification inbox and the tutoring marketplace. They stay reachable when a lead is not.
 */
export const OWN_ACCOUNT_PATH = /^\/teacher\/(team|billing|settings|notifications|tutoring)(\/|$)/

export function leadAccess(
  lead: { permissions: readonly TeamPermission[] } | null,
  classListError: unknown,
  pathname: string,
): LeadAccess {
  if (lead === null || OWN_ACCOUNT_PATH.test(pathname)) return "ok"
  if (looksLikeTeamLeadUnavailable(classListError)) return "unavailable"
  if (looksLikeTeamPermissionDenied(classListError)) {
    return lead.permissions.includes("view_results") ? "unavailable" : "no-view"
  }
  return "ok"
}
